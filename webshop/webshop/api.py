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
from webshop.webshop.shopping_cart.cart import get_party, get_address_docs
from webshop.webshop.doctype.wishlist.wishlist import add_to_wishlist 
from webshop.webshop.doctype.wishlist.wishlist import remove_from_wishlist
from frappe import  _
from frappe.utils.password import update_password as _update_password
from frappe.website.utils import is_signup_disabled
from frappe.utils import (
	escape_html,
)

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
	}


@frappe.whitelist(allow_guest=True)
def get_guest_redirect_on_action():
	return frappe.db.get_single_value("Webshop Settings", "redirect_on_action")


@frappe.whitelist(allow_guest=True)
def get_main_group():
	return get_main_groups_for_website()


@frappe.whitelist()
def get_orders():
    party = get_party()
    lp_record = frappe.get_all("Sales Invoice", filters={"customer": party.name}, fields=["name","status","base_total","company","customer_name","creation"])
    for invoice in lp_record:
       items = frappe.get_all("Sales Invoice Item",filters={"parent": invoice["name"]},fields=["item_code", "item_name", "qty", "rate", "amount"])
       invoice["items"] = items
    return lp_record


@frappe.whitelist()
def get_shipping_methods():
    party = get_party()
    lp_record = frappe.get_all("Shipping Rule", filters={"custom_show_on_website": 1}, fields=["name","shipping_rule_type","shipping_amount"])
    return lp_record




@frappe.whitelist(allow_guest=True)
def edit_product_wish(
	name: str = None,
	wished: bool = None,
):
	if wished:
		add_to_wishlist(name)
	else:
		remove_from_wishlist(name)


@frappe.whitelist(allow_guest=True)
def sign_up(email: str, full_name: str, redirect_to: str) -> tuple[int, str]:
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

		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": escape_html(full_name),
				"enabled": 1,
				"new_password": random_string(10),
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
            
            
  
		api_secret = frappe.generate_hash(length=15)
		if not user.api_key:
			api_key = frappe.generate_hash(length=15)
			user.api_key = api_key
			user.api_secret = api_secret 
			user.save()
			user.reload()
		token = f"{user.api_key}:{user.get_password('api_secret')}"
		return {"message":'Logged In',"token":token}
