from django.contrib import admin
from whats_fresh_api.models import Image

class ImageAdmin(admin.ModelAdmin):
    readonly_fields = ('created', 'modified')

admin.site.register(Image, ImageAdmin)