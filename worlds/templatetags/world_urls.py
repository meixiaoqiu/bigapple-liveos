from django import template
from worlds.routing import world_reverse


register = template.Library()


@register.simple_tag(takes_context=True)
def world_url(context, viewname: str, *args: object) -> str:
    request = context.get("request")
    if request is None:
        return ""
    return world_reverse(request, viewname, *args)
