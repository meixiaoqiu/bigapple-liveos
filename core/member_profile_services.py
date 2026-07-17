"""Self-service public profile maintenance for workspace members."""

from __future__ import annotations

from core.models import Member, MemberPublicProfile


def update_member_public_profile(
    *,
    member: Member,
    public_name: str,
    avatar_url: str,
) -> MemberPublicProfile:
    """Update the public name and avatar that the member exposes in Observer.

    Validates-before-save: if avatar_url fails URLField validation the
    existing profile (if any) is NOT overwritten and the error propagates.
    bio and is_visible are not editable from workspace — only Observer-
    facing display fields are touched here.
    """
    cleaned_name = (public_name or "").strip()[:255]
    cleaned_url = (avatar_url or "").strip()[:1000]

    profile = MemberPublicProfile.objects.filter(member=member).first()
    if profile is None:
        profile = MemberPublicProfile(member=member, is_visible=True, public_name=cleaned_name, avatar_url=cleaned_url)
        profile.full_clean()
        profile.save()  # INSERT — no update_fields on new object
    else:
        profile.public_name = cleaned_name
        profile.avatar_url = cleaned_url
        profile.full_clean()
        profile.save(update_fields=["public_name", "avatar_url", "updated_at"])
    return profile
