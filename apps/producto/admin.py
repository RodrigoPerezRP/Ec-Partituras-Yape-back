from django.contrib import admin
from .models import Producto, CategoriaProducto


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = (
        'nombre',
        'precio',
        'dificultad',
        'arreglista',
        'tieneDestacado',
        'tieneAudio',
        'tieneFinale',
        'datecreated',
        'categoria',
        'uuidCode',
    )

    list_filter = (
        'dificultad',
        'tieneDestacado',
        'tieneAudio',
        'tieneFinale',
        'datecreated',
    )

    search_fields = (
        'nombre',
        'descripcion',
        'arreglista',
    )

    prepopulated_fields = {
        'slug': ('nombre',)
    }

    ordering = ('-datecreated',)

    readonly_fields = ('datecreated',)

    fieldsets = (
        ('Información básica', {
            'fields': (
                'nombre',   
                'slug',
                'descripcion',
                'precio',
                'dificultad',
                'arreglista',
                'categoria',
                'uuidCode',
            )
        }),
        ('Multimedia', {
            'fields': (
                'portada',
                'tieneAudio',
                'tieneFinale',
                'archivo',
            )
        }),
        ('Estado', {
            'fields': (
                'tieneDestacado',
                'datecreated',
            )
        }),
    )

admin.site.register(CategoriaProducto)