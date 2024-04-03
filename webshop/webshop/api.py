# -*- coding: utf-8 -*-
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.utils import cint

from webshop.webshop.product_data_engine.filters import ProductFiltersBuilder
from webshop.webshop.product_data_engine.query import ProductQuery
from webshop.webshop.doctype.override_doctype.item_group import get_child_groups_for_website
from webshop.webshop.doctype.override_doctype.item_group import get_main_groups_for_website
from webshop.webshop.shopping_cart.cart import get_party, update_cart as _update_cart
from webshop.webshop.doctype.wishlist.wishlist import add_to_wishlist 
from webshop.webshop.doctype.wishlist.wishlist import remove_from_wishlist
from frappe.utils.oauth import  redirect_post_login
from frappe import  _
from frappe.utils.password import update_password as _update_password
from frappe.website.utils import is_signup_disabled
from frappe.utils import (
	escape_html,
)
from webshop.webshop.shopping_cart.cart import (_get_cart_quotation)
from frappe.utils import nowdate, nowtime, cint


@frappe.whitelist(allow_guest=True)
def get_product_filter_data(query_args=None):
	"""
	Returns filtered products and discount filters.

	Args:
		query_args (dict): contains filters to get products list

	Query Args filters:
		search (str): Search Term.
		field_filters (dict): Keys include item_group, brand, etc.
		attribute_filters(dict): Keys include Color, Size, etc.
		start (int): Offset items by
		item_group (str): Valid Item Group
		from_filters (bool): Set as True to jump to page 1
	"""
	if isinstance(query_args, str):
		query_args = json.loads(query_args)

	query_args = frappe._dict(query_args)

	if query_args:
		search = query_args.get("search")
		field_filters = query_args.get("field_filters", {})
		attribute_filters = query_args.get("attribute_filters", {})
		start = cint(query_args.start) if query_args.get("start") else 0
		item_group = query_args.get("item_group")
		from_filters = query_args.get("from_filters")
	else:
		search, attribute_filters, item_group, from_filters = None, None, None, None
		field_filters = {}
		start = 0

	# if new filter is checked, reset start to show filtered items from page 1
	if from_filters:
		start = 0

	sub_categories = []
	if item_group:
		sub_categories = get_child_groups_for_website(item_group, immediate=True)

	engine = ProductQuery()

	try:
		result = engine.query(
			attribute_filters,
			field_filters,
			search_term=search,
			start=start,
			item_group=item_group,
		)
	except Exception:
		print(frappe.get_traceback())
		frappe.log_error("Product query with filter failed")
		return {"exc": "Something went wrong!"}

	# discount filter data
 
	filters = {}
	discounts = result["discounts"]

	if discounts:
		filter_engine = ProductFiltersBuilder()
		filters["discount_filters"] = filter_engine.get_discount_filters(discounts)
            
    

	return {
		"items": result["items"] or [],
		"filters": filters,
		"settings": engine.settings,
		"sub_categories": sub_categories,
		"items_count": result["items_count"],
        "total_items" : frappe.db.count('Website Item', {'published': '1'})
	}


@frappe.whitelist(allow_guest=True)
def get_guest_redirect_on_action():
	return frappe.db.get_single_value("Webshop Settings", "redirect_on_action")


@frappe.whitelist(allow_guest=True)
def get_main_group():
	return get_main_groups_for_website()


@frappe.whitelist()
def get_orders(filters="{}", start=0, page_size=20):
    party = get_party()
    filters = json.loads(filters)
    filters = {
        **filters,
        "customer": party.name,
    }
    order_list = frappe.db.get_all(
         "Sales Order",
         filters=filters,
         fields="*",
        limit_start=start,
        limit_page_length=page_size,
    )
    count = frappe.db.count("Sales Order", filters=filters)
    return {
        "orders": order_list,
        "count": count,
    }

@frappe.whitelist()
def get_order(order_name):
    party = get_party()
    sales_order = frappe.get_last_doc("Sales Order", filters={"name": order_name, "customer": party.name})
    if not sales_order:
        frappe.throw(_("You are not allowed to access this order"))
    return sales_order

@frappe.whitelist()
def get_shipping_methods():
    party = get_party()
    lp_record = frappe.get_all("Shipping Rule", filters={"custom_show_on_website": 1}, fields=["name","shipping_rule_type","shipping_amount"])
    return lp_record




@frappe.whitelist()
def update_wshlist(
	item_codes: list = [],
):
    if frappe.db.exists("Wishlist", frappe.session.user):
        wishlist = frappe.get_doc("Wishlist", frappe.session.user)
        wishlist.items = []
        wishlist.save(ignore_permissions=True)
    for item_code in item_codes:
        add_to_wishlist(item_code)  
    return item_codes


@frappe.whitelist(allow_guest=True)
def sign_up(email: str, full_name: str, password):
    if is_signup_disabled():
        frappe.throw(_("Sign Up is disabled"), title=_("Not Allowed"))

    user = frappe.db.get("User", {"email": email})
    if user:
        if user.enabled:
            return 0, _("Already Registered")
        else:
            return 0, _("Registered but disabled")
    else:
        if frappe.db.get_creation_count("User", 60) > 300:
            frappe.respond_as_web_page(
                _("Temporarily Disabled"),
                _(
                    "Too many users signed up recently, so the registration is disabled. Please try back in an hour"
                ),
                http_status_code=429,
            )

        from frappe.utils import random_string
        at_index = email.find("@")
        username = ''
        if at_index != -1:
            username = email[:at_index]
            
        base_username = username
        count = 1
        while frappe.db.get_value("User", {"username": username}):
            count += 1
            username = f"{base_username}{count}"
            

        user = frappe.get_doc(
            {
                "doctype": "User",
                "email": email,
                "first_name": escape_html(full_name),
                "username": username,
                "enabled": 1,
                "new_password": password,
                "user_type": "Website User",
            }
        )
        user.flags.ignore_permissions = True
        user.flags.ignore_password_policy = True
        user.flags.is_verified  = 1
        user.insert()

        default_role = frappe.db.get_single_value("Portal Settings", "default_role")
        if default_role:
            user.add_roles(default_role)
        
        # api_secret = frappe.generate_hash(length=15)
        # if not user.api_key:
        #     api_key = frappe.generate_hash(length=15)
        #     user.api_key = api_key
        #     user.api_secret = api_secret 
        #     user.save()
        #     user.reload()

        # token = f"{user.api_key}:{user.get_password('api_secret')}"

        # use Login Manager to login
        frappe.local.login_manager.login_as(user.name)

        return {
             "user": user.name,
             "username": user.username,
             "full_name": user.full_name,
             "email": user.email
        }


@frappe.whitelist()
def update_cart(cart):
    quotation = _get_cart_quotation()
    if not quotation.as_dict().get("__islocal", 0):
        for item in quotation.items:
            frappe.delete_doc("Quotation Item", item.name, ignore_permissions=True)
        quotation.save(ignore_permissions=True)
    for item_code, qty in cart.items():
        _update_cart(item_code, qty)
    return _get_cart_quotation()
    
    
@frappe.whitelist()
def update_profile(first_name=None, last_name=None, phone=None):
    user = frappe.get_doc("User", frappe.session.user)
    if first_name is not None:
        user.first_name = first_name
    if last_name is not None:
        print("last_name", last_name)
        user.last_name = last_name
    if phone is not None:
        user.phone = phone
    user.flags.ignore_permissions = True
    user.save()
    
@frappe.whitelist()
def payment_info():
    payments = frappe.get_doc("Storefront Website Settings", "Storefront Website Settings")
    
    payment_methods = []
    
    if payments.enable_promptpay_qr == 1:
        payment_info = {
            'name': payments.payment_method_title,
            'key': 1,
            'promptpay_qr_image': payments.upload_your_promptpay_qr_image,
            'account_name': payments.promptpay_account_name,
            'promptpay_number': payments.promptpay_number
        }
        payment_methods.append(payment_info)
        
    if payments.enable_bank_transfer == 1:
        banks_list = frappe.get_all("Payment channel",filters={"parent": "Storefront Website Settings"},fields=["bank","bank_account_name","bank_account_number"])
        payment_info = {
            'name': payments.bank_title,
            'key': 2,
            'banks_list': banks_list
        }
        payment_methods.append(payment_info)
    
    return payment_methods


@frappe.whitelist()
def payment_entry(file, order_name, payment_info):
    if order_name:
        get_si = frappe.get_doc("Sales Invoice", order_name)
        payment_id = get_si.custom_payment_method
        web_settings = frappe.get_doc("Storefront Website Settings", "Storefront Website Settings")
        mode_of_payment = ""
        if payment_id == 1:
            mode_of_payment = web_settings.mode_of_payment_for_qr
        elif payment_id == 2:
            mode_of_payment = web_settings.mode_of_payment_for_bank
        _make_payment_entry(get_si, mode_of_payment, get_si.base_grand_total)
    
def _make_payment_entry(si, mode_of_payment, paid_amount):
    
    pe = frappe.new_doc('Payment Entry')
    pe.update({
        'payment_type': 'Receive',
        'posting_date': nowdate(),
        'posting_time': nowtime(),
        'mode_of_payment': mode_of_payment,
        'paid_amount': paid_amount,
        'received_amount': paid_amount,
        'allocate_payment_amount': 1,
        'party_type': 'Customer',
        'party': si.customer,
        'paid_from': si.debit_to,
        "target_exchange_rate":1,
        'paid_to': 'Cash - Z'
    })
    ffa = paid_amount
    pe.append('references', {
                'reference_doctype': 'Sales Invoice',
                'reference_name': si.name,
                'allocated_amount': ffa
        })
    pe.save(ignore_permissions=True)