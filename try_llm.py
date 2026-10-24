"""Run the LLM functions on the test fixtures: python try_llm.py"""
import asyncio
import json

import llm

BUSINESS_TRANSCRIPT = (
    "I am electrician, I am available 24/7, during 8am-5pm it costs 30 eur minimum callout and otherwise "
    "150 eur minimum callout. Everything else will be quoted directly to client."
)
CLIENT_REQUEST = "I want an electrician any weekday after 4pm"


def show(title, obj):
    print(f"\n===== {title} =====")
    print(json.dumps(obj, ensure_ascii=False, indent=2))


async def main():
    profile = await llm.extract_business_profile(BUSINESS_TRANSCRIPT)
    show("extract_business_profile", profile.model_dump())
    assert profile.trade == "electrician"
    assert profile.availability_json.always_available

    updated = await llm.update_business_profile(
        {**profile.model_dump(), "missing": None}, "My name is Andreas Volt and I work in Limassol"
    )
    show("update_business_profile", updated.model_dump())
    assert updated.name and updated.area

    request = await llm.extract_client_request(f"Client: {CLIENT_REQUEST}")
    show("extract_client_request", request.model_dump())
    assert request.trade == "electrician"

    candidate = {"id": 1, **updated.model_dump()}
    matches = await llm.match_businesses(request.model_dump(), [candidate])
    show("match_businesses", [m.model_dump() for m in matches])
    assert matches and matches[0].available

    print("\nAll fixture checks passed.")


if __name__ == "__main__":
    asyncio.run(main())
