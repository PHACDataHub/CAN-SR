import asyncio


def test_smoke():
    assert False



async def test_my_async_code():
    result = await asyncio.sleep(0.01, result="success")
    assert result == "success"