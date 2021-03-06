from django.http import (HttpResponse, HttpResponseRedirect)
from django.shortcuts import render
from django.core.urlresolvers import reverse
from django.utils.datastructures import MultiValueDictKeyError
from django.contrib.gis.geos import fromstr
from django.shortcuts import get_object_or_404
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth.decorators import login_required
from django.conf import settings

from whats_fresh.whats_fresh_api.models import (Vendor, Product,
                                                ProductPreparation,
                                                VendorProduct)
from whats_fresh.whats_fresh_api.forms import VendorForm
from whats_fresh.whats_fresh_api.functions import (group_required,
                                                   coordinates_from_address,
                                                   BadAddressException)

import json


@login_required
@group_required('Administration Users', 'Data Entry Users')
def vendor(request, id=None):
    """
    */entry/vendors/<id>*, */entry/vendors/new*

    The entry interface's edit/add/delete vendor view. This view creates the
    edit page for a given vendor, or the "new vendor" page if it is not passed
    an ID. It also accepts POST requests to create or edit vendors, and DELETE
    requests to delete the vendor.

    If called with DELETE, it will return a 200 upon success or a 404 upon
    failure. This is to be used as part of an AJAX call, or some other API
    call.
    """
    if request.method == 'DELETE':
        vendor = get_object_or_404(Vendor, pk=id)
        vendor.delete()
        return HttpResponse()

    if request.method == 'POST':
        post_data = request.POST.copy()
        errors = []

        try:
            coordinates = coordinates_from_address(
                post_data['street'], post_data['city'], post_data['state'],
                post_data['zip'])

            post_data['location'] = fromstr(
                'POINT(%s %s)' % (coordinates[1], coordinates[0]),
                srid=4326)
        # Bad Address will be thrown if Google does not return coordinates for
        # the address, and MultiValueDictKeyError will be thrown if the POST
        # data being passed in is empty.
        except (MultiValueDictKeyError, BadAddressException):
            errors.append("Full address is required.")

        try:
            if not post_data['preparation_ids']:
                errors.append("You must choose at least one product.")
                prod_preps = []
            else:
                prod_preps = list(
                    set(post_data['preparation_ids'].split(',')))
                # TODO: Find better way to do form validation
                # Needed for form validation to pass
                post_data['products_preparations'] = prod_preps[0]

        except MultiValueDictKeyError:
            errors.append("You must choose at least one product.")
            prod_preps = []

        vendor_form = VendorForm(post_data)
        if vendor_form.is_valid() and not errors:
            del vendor_form.cleaned_data['products_preparations']
            if id:
                vendor = Vendor.objects.get(id=id)

                # For all of the current vendor products,
                for vendor_product in vendor.vendorproduct_set.all():
                    # Delete any that aren't in the returned list
                    if vendor_product.product_preparation.id not in prod_preps:
                        vendor_product.delete()
                    # And ignore any that are in both the existing and the
                    # returned list
                    elif vendor_product.product_preparation.id in prod_preps:
                        prod_preps.remove(
                            vendor_product.product_preparation.id)
                # Then, create all of the new ones
                for product_preparation in prod_preps:
                    vendor_product = VendorProduct.objects.create(
                        vendor=vendor,
                        product_preparation=ProductPreparation.objects.get(
                            id=product_preparation))
                vendor.__dict__.update(**vendor_form.cleaned_data)
                vendor.save()
            else:
                vendor = Vendor.objects.create(**vendor_form.cleaned_data)
                for product_preparation in prod_preps:
                    vendor_product = VendorProduct.objects.create(
                        vendor=vendor,
                        product_preparation=ProductPreparation.objects.get(
                            id=product_preparation))
                vendor.save()
            return HttpResponseRedirect(
                "%s?saved=true" % reverse('list-vendors-edit'))

        existing_prod_preps = []
        for preparation_id in prod_preps:
            product_preparation_object = ProductPreparation.objects.get(
                id=preparation_id)
            existing_prod_preps.append({
                'id': preparation_id,
                'preparation_text':
                    product_preparation_object.preparation.name,
                'product': product_preparation_object.product.name
            })
    else:
        existing_prod_preps = []
        errors = []

    if id:
        vendor = Vendor.objects.get(id=id)
        vendor_form = VendorForm(instance=vendor)
        title = "Edit %s" % vendor.name
        message = ""
        post_url = reverse('edit-vendor', kwargs={'id': id})
        # If the list already has items, we're coming back to it from above
        # And have already filled the list with the product preparations POSTed
        if not existing_prod_preps:
            for vendor_product in vendor.vendorproduct_set.all():
                existing_prod_preps.append({
                    'id': vendor_product.product_preparation.id,
                    'preparation_text':
                        vendor_product.product_preparation.preparation.name,
                    'product': vendor_product.product_preparation.product.name
                })
    elif request.method != 'POST':
        title = "Add a Vendor"
        post_url = reverse('new-vendor')
        message = "* = Required field"
        vendor_form = VendorForm()
    else:
        title = "Add aVendor"
        message = "* = Required field"
        post_url = reverse('new-vendor')

    data = {}
    product_list = []

    for product in Product.objects.all():
        product_list.append(product.name)
        data[str(product.name)] = []
        for preparation in product.productpreparation_set.all():
            data[str(product.name)].append({
                "value": preparation.id,
                "name": preparation.preparation.name
            })

    json_preparations = json.dumps(data)

    return render(request, 'vendor.html', {
        'parent_url': [
            {'url': reverse('home'), 'name': 'Home'},
            {'url': reverse('list-vendors-edit'), 'name': 'Vendors'}],
        'title': title,
        'message': message,
        'post_url': post_url,
        'existing_product_preparations': existing_prod_preps,
        'errors': errors,
        'vendor_form': vendor_form,
        'json_preparations': json_preparations,
        'product_list': product_list,
    })


@login_required
@group_required('Administration Users', 'Data Entry Users')
def vendor_list(request):
    """
    */entry/vendors*

    The entry interface's vendors list. This view lists all vendors,
    their description, and allows you to click on them to view/edit the
    vendor.
    """

    message = ""
    if request.GET.get('success') == 'true':
        message = "Vendor deleted successfully!"
    elif request.GET.get('saved') == 'true':
        message = "Vendor saved successfully!"

    paginator = Paginator(Vendor.objects.order_by('name'),
                          settings.PAGE_LENGTH)
    page = request.GET.get('page')

    try:
        vendors = paginator.page(page)
    except PageNotAnInteger:
        # If page is not an integer, deliver first page.
        vendors = paginator.page(1)
    except EmptyPage:
        # If page is out of range (e.g. 9999), deliver last page of results.
        vendors = paginator.page(paginator.num_pages)

    return render(request, 'list.html', {
        'parent_url': reverse('home'),
        'parent_text': 'Home',
        'message': message,
        'new_url': reverse('new-vendor'),
        'new_text': "New Vendor",
        'title': "All Vendors",
        'item_classification': "vendor",
        'item_list': vendors,
        'edit_url': 'edit-vendor'
    })
