"""Self-service public profile maintenance for workspace members."""

from __future__ import annotations

from core.models import Member, MemberPublicProfile


def update_member_public_profile(
    *,
    member: Member,
    public_name: str,
) -> MemberPublicProfile:
    """Update the public name that the member exposes in Observer."""
    cleaned_name = (public_name or "").strip()[:255]

    profile = MemberPublicProfile.objects.filter(member=member).first()
    if profile is None:
        profile = MemberPublicProfile(member=member, is_visible=True, public_name=cleaned_name)
        profile.full_clean()
        profile.save()  # INSERT — no update_fields on new object
    else:
        profile.public_name = cleaned_name
        profile.full_clean()
        profile.save(update_fields=["public_name", "updated_at"])
    return profile
