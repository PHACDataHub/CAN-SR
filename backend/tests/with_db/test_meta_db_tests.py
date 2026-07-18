from api.services.user_db import UserDatabaseService, user_db_service
from api.models.auth import UserCreate
from api.services.sr_db_service import SRDBService, srdb_service


async def test_user_table_clean():
    users = await user_db_service.get_all_users()
    assert len(users) == 0

async def test_create_user():
    u = await user_db_service.get_user_by_email("a@b.com")
    assert u is None

    created = await user_db_service.create_user(
        UserCreate(
            email="a@b.com",
            full_name="Test User",
            password="password123",
        )
    )

    assert created is not None
    assert created.email == "a@b.com"


    u = await user_db_service.get_user_by_email("a@b.com")
    assert u is not None


async def test_user_from_other_test_doesnt_exist():
    # this should ensure that the database is clean before each test
    u = await user_db_service.get_user_by_email("a@b.com")
    assert u is None


def test_synchronous_db_api():
    current = srdb_service.list_systematic_reviews_for_user("a@b.com")
    assert len(current) == 0

    created = srdb_service.create_systematic_review(
        name="Test SR",
        description="A test systematic review",
        criteria_str="Test inclusion/exclusion criteria",
        criteria_obj={"inclusion": ["Test inclusion criteria"], "exclusion": ["Test exclusion criteria"]},
        owner_id="1",
        owner_email="a@b.com",
    )
def test_synchronous_db_api_reset_after_transaction():
    current = srdb_service.list_systematic_reviews_for_user("a@b.com")
    assert len(current) == 0


async def test_mixing_sync_and_async_db_calls():
    """
    This test shows that mixing sync and async calls doesn't raise exceptions 

    It's probably still a bad idea
    """
    
    current = srdb_service.list_systematic_reviews_for_user("a@b.com")
    assert len(current) == 0

    users = await user_db_service.get_all_users()
    assert len(users) == 0

    created = await user_db_service.create_user(
        UserCreate(
            email="a@b.com",
            full_name="Test User",
            password="password123",
        )
    )

    sr = srdb_service.create_systematic_review(
        name="Test SR",
        description="A test systematic review",
        criteria_str="Test inclusion/exclusion criteria",
        criteria_obj={"inclusion": ["Test inclusion criteria"], "exclusion": ["Test exclusion criteria"]},
        owner_id="1",
        owner_email="a@b.com",
    )

    user = await user_db_service.get_user_by_email("a@b.com")
    assert user is not None

    sr = srdb_service.get_systematic_review(sr['id'])
    assert sr is not None


            

