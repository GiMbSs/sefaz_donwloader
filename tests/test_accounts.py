import pytest

from apps.accounts.models import User


@pytest.mark.django_db
def test_user_is_created_with_email_as_identifier():
    user = User.objects.create_user("OPERADOR@EXAMPLE.COM", "strong-password")

    assert user.email == "OPERADOR@example.com"
    assert user.check_password("strong-password")
    assert user.get_full_name() == "OPERADOR@example.com"

