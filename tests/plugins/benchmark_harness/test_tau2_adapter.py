import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from plugins.benchmark_harness.tau2_geode_agent import (
    GeodeTau2State,
    RetailWritePreflight,
    _agent_system_prompt,
    _assert_tau2_route_ready,
    _codex_empty_text_dumps,
    _compose_agent_candidate_surface,
    _dedupe_duplicate_tool_calls,
    _drop_premature_transfer_from_read_bundle,
    _hydrate_workflow_order_from_history,
    _load_agent_guard,
    _load_agent_planner,
    _observe_workflow_result_tool_outputs,
    _post_text_projection_enabled,
    _project_account_identity_lookup_from_workflow_order,
    _project_account_roaming_repair_from_prompt,
    _project_account_roaming_repair_from_workflow_order,
    _project_data_refuel_from_workflow_order,
    _project_data_usage_lookup_from_workflow_order,
    _project_line_detail_lookup_from_workflow_order,
    _project_phone_number_from_user_instructions,
    _project_retail_pending_item_writes_from_workflow_order,
    _project_retail_return_writes_from_workflow_order,
    _project_user_actions_after_observed_text,
    _project_user_actions_for_premature_terminal,
    _projected_user_identity_text,
    _raise_on_new_codex_empty_text_dumps,
    _run_geode_turn_with_empty_text_retry,
    _tau2_tool_calls,
    _trajectory_snapshot_paths,
    _user_projector_workflow_order,
    _user_system_prompt,
    _workflow_user_projection_ready,
    _write_trajectory_snapshot,
)
from plugins.benchmark_harness.tau2_workflow_order import (
    TelecomMmsWorkflowOrder,
    build_workflow_order_scaffold,
)


def test_tau2_agent_prompt_blocks_inferred_optional_tool_args() -> None:
    prompt = _agent_system_prompt("Policy body")

    assert "leave optional arguments unset" in prompt
    assert "unless the user, the policy, or a prior tool result explicitly supplied" in prompt
    assert "Do not add inferred descriptions" in prompt
    assert "Policy body" in prompt


def test_tau2_agent_prompt_appends_crucible_guard() -> None:
    prompt = _agent_system_prompt(
        "Policy body",
        guard_id="t1",
        guard_text="T1 telecom workflow-completion guard:\nVerify MMS terminal state.",
    )

    assert '<crucible_candidate_guard id="t1">' in prompt
    assert "T1 telecom workflow-completion guard" in prompt
    assert "Verify MMS terminal state." in prompt
    assert prompt.index("<policy>") < prompt.index("<crucible_candidate_guard")


def test_tau2_r1_guard_keeps_split_payment_on_retail_fallback_ladder() -> None:
    guard_id, guard_text = _load_agent_guard("r1", None)

    assert guard_id == "r1"
    assert "split payment" in guard_text
    assert "most expensive item and its price" in guard_text
    assert "same-product cheaper variants" in guard_text
    assert "cancel the pending order" in guard_text


def test_tau2_retail_split_payment_workflow_order_surface() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-split-payment-v1")
    assert scaffold is not None
    scaffold.observe_incoming_message(
        SimpleNamespace(
            content=("I cannot use split payment and need the order under my card budget.")
        )
    )
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W9348897",
                "status": "pending",
                "items": [
                    {"name": "Action Camera", "price": 481.5},
                    {"name": "Desk Lamp", "price": 150.01},
                ],
                "payment_history": [
                    {"transaction_type": "payment", "amount": 1166.98},
                ],
            }
        ),
    )

    hint = scaffold.prompt_hint()

    assert "Action Camera" in hint
    assert "$481.50" in hint
    assert "466.75 + 288.82 + 135.24 + 193.38 + 46.66" in hint
    assert "reason no longer needed" in hint
    assert scaffold.branch_correction_prompt("I can cancel it.") is not None


def test_tau2_retail_split_payment_correction_requires_split_payment_request() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-split-payment-v1")
    assert scaffold is not None
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W9373487",
                "status": "pending",
                "items": [{"name": "Portable Charger", "price": 109.27}],
            }
        ),
    )

    assert scaffold.branch_correction_prompt("Here is the tracking number.") is None


def test_tau2_retail_workflow_order_blocks_premature_lost_item_transfer() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_incoming_message(
        SimpleNamespace(
            content=(
                "I lost my tablet. Can you find the tracking number and tell me if "
                "a refund or reorder is possible?"
            )
        )
    )
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W2692684",
                "items": [{"name": "Tablet", "item_id": "3788616824"}],
                "status": "delivered",
                "fulfillments": [
                    {
                        "tracking_id": ["746342064230"],
                        "item_ids": ["3788616824"],
                    }
                ],
            }
        ),
    )

    assert scaffold.premature_terminal_tool("transfer_to_human_agents") is True
    correction = scaffold.premature_transfer_correction_prompt()
    assert correction is not None
    assert "746342064230" in correction
    assert "CANNOT call transfer_to_human_agents yet" in correction
    assert "pending order cancellation or delivered-item return/exchange" in correction
    assert "inspect the user's known orders" in correction


def test_tau2_retail_contingent_intent_hint_requires_order_detail_before_write() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None

    hint = scaffold.prompt_hint()

    assert "order-id list is only a locator" in hint
    assert "CANNOT list item names" in hint
    assert "get_order_details" in hint


def test_tau2_retail_account_address_claim_requires_user_address_write() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_user_text(
        "Please fix my account address and update my pending orders to "
        "445 Maple Drive, Suite 394, Fort Worth, TX 76165."
    )
    scaffold.observe_tool_output(
        "get_user_details",
        json.dumps({"user_id": "olivia_lopez_3865"}),
    )
    scaffold.observe_outgoing_tool_calls(
        [
            SimpleNamespace(
                name="modify_pending_order_address",
                arguments={
                    "order_id": "#W9583042",
                    "address1": "445 Maple Drive",
                    "address2": "Suite 394",
                    "city": "Fort Worth",
                    "state": "TX",
                    "country": "USA",
                    "zip": "76165",
                },
            )
        ]
    )

    correction = scaffold.branch_correction_prompt(
        "Your default account address and pending order were updated."
    )

    assert correction is not None
    assert "modify_user_address" in correction
    assert "olivia_lopez_3865" in correction
    assert "445 Maple Drive" in correction
    assert "CANNOT claim completion" in correction


def test_tau2_retail_account_address_claim_allows_after_user_address_write() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_user_text("Please fix my default address.")
    scaffold.observe_outgoing_tool_calls(
        [
            SimpleNamespace(
                name="modify_user_address",
                arguments={
                    "user_id": "olivia_lopez_3865",
                    "address1": "445 Maple Drive",
                    "address2": "Suite 394",
                    "city": "Fort Worth",
                    "state": "TX",
                    "country": "USA",
                    "zip": "76165",
                },
            )
        ]
    )

    assert scaffold.branch_correction_prompt("Your default address has been updated.") is None


def test_tau2_retail_account_address_projector_emits_confirmed_writes() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_tool_output(
        "get_user_details",
        json.dumps({"user_id": "mei_patel_7272"}),
    )
    scaffold.observe_user_text(
        "It should be 445 Maple Drive, Suite 394, Fort Worth, Texas 76165. "
        "Please update both my account address and any order addresses that need it."
    )
    for order_id in ("#W9583042", "#W4082615"):
        scaffold.observe_tool_output(
            "get_order_details",
            json.dumps(
                {
                    "order_id": order_id,
                    "status": "pending",
                    "address": {
                        "address1": "443 Maple Drive",
                        "address2": "Suite 394",
                        "city": "Fort Worth",
                        "state": "TX",
                        "country": "USA",
                        "zip": "76165",
                    },
                }
            ),
        )
    scaffold.observe_user_text("Yes, please update them to that address.")

    actions = scaffold.projected_retail_address_writes()

    assert [name for name, _arguments in actions] == [
        "modify_pending_order_address",
        "modify_pending_order_address",
        "modify_user_address",
    ]
    assert actions[0][1]["order_id"] == "#W9583042"
    assert actions[1][1]["order_id"] == "#W4082615"
    assert actions[2][1]["user_id"] == "mei_patel_7272"
    assert all(arguments["address1"] == "445 Maple Drive" for _name, arguments in actions)
    assert all(arguments["state"] == "TX" for _name, arguments in actions)


def test_tau2_retail_return_projector_emits_all_except_delivered_return() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_user_text(
        "I want to return everything in the delivered order except the tablet. "
        "How much money can I get back?"
    )
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W1679211",
                "status": "delivered",
                "items": [
                    {"name": "Tablet", "item_id": "4913411651", "price": 941.03},
                    {"name": "E-Reader", "item_id": "6268080249", "price": 244.02},
                    {"name": "Jigsaw Puzzle", "item_id": "7127170374", "price": 52.03},
                    {"name": "T-Shirt", "item_id": "9612497925", "price": 50.88},
                ],
                "payment_history": [
                    {
                        "transaction_type": "payment",
                        "amount": 1287.96,
                        "payment_method_id": "paypal_3022415",
                    }
                ],
            }
        ),
    )

    actions = _project_retail_return_writes_from_workflow_order(scaffold)

    assert actions == [
        (
            "return_delivered_order_items",
            {
                "order_id": "#W1679211",
                "item_ids": ["6268080249", "7127170374", "9612497925"],
                "payment_method_id": "paypal_3022415",
            },
        )
    ]


def test_tau2_retail_return_projector_dedupes_issued_order_return() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_user_text("I want to return everything but the tablet.")
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W1679211",
                "status": "delivered",
                "items": [
                    {"name": "Tablet", "item_id": "4913411651"},
                    {"name": "E-Reader", "item_id": "6268080249"},
                ],
                "payment_history": [
                    {
                        "transaction_type": "payment",
                        "payment_method_id": "paypal_3022415",
                    }
                ],
            }
        ),
    )
    scaffold.observe_outgoing_tool_calls(
        [
            SimpleNamespace(
                name="return_delivered_order_items",
                arguments={
                    "order_id": "#W1679211",
                    "item_ids": ["6268080249"],
                    "payment_method_id": "paypal_3022415",
                },
            )
        ]
    )

    assert _project_retail_return_writes_from_workflow_order(scaffold) == []


def test_tau2_retail_source_address_bundle_projector_emits_confirmed_writes() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_user_text(
        "I placed a luggage set order to my new address. Please update another "
        "order's shipping address to the new home, make it my default address, "
        "and exchange my tablet for the cheapest tablet option."
    )
    scaffold.observe_tool_output(
        "get_user_details",
        json.dumps({"user_id": "sophia_martin_8570"}),
    )
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W1603792",
                "status": "pending",
                "address": {
                    "address1": "760 Elm Avenue",
                    "address2": "Suite 564",
                    "city": "Houston",
                    "country": "USA",
                    "state": "TX",
                    "zip": "77034",
                },
                "items": [
                    {
                        "name": "Tablet",
                        "product_id": "8024098596",
                        "item_id": "6501071631",
                        "price": 1018.68,
                    }
                ],
                "payment_history": [
                    {
                        "transaction_type": "payment",
                        "payment_method_id": "credit_card_5694100",
                    }
                ],
            }
        ),
    )
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W1092119",
                "status": "pending",
                "address": {
                    "address1": "592 Elm Avenue",
                    "address2": "Suite 978",
                    "city": "Houston",
                    "country": "USA",
                    "state": "TX",
                    "zip": "77242",
                },
                "items": [{"name": "Luggage Set", "item_id": "6690069155"}],
                "payment_history": [
                    {
                        "transaction_type": "payment",
                        "payment_method_id": "credit_card_5694100",
                    }
                ],
            }
        ),
    )
    scaffold.observe_tool_output(
        "get_product_details",
        json.dumps(
            {
                "product_id": "8024098596",
                "variants": {
                    "2106335193": {
                        "item_id": "2106335193",
                        "available": True,
                        "price": 903.95,
                    },
                    "9999999999": {
                        "item_id": "9999999999",
                        "available": True,
                        "price": 990.01,
                    },
                },
            }
        ),
    )
    scaffold.observe_user_text("Yes, please proceed with all three changes.")

    address_actions = scaffold.projected_retail_address_writes()
    item_actions = _project_retail_pending_item_writes_from_workflow_order(scaffold)

    assert [name for name, _arguments in address_actions] == [
        "modify_pending_order_address",
        "modify_user_address",
    ]
    assert address_actions[0][1]["order_id"] == "#W1603792"
    assert address_actions[0][1]["address1"] == "592 Elm Avenue"
    assert address_actions[1][1]["user_id"] == "sophia_martin_8570"
    assert item_actions == [
        (
            "modify_pending_order_items",
            {
                "order_id": "#W1603792",
                "item_ids": ["6501071631"],
                "new_item_ids": ["2106335193"],
                "payment_method_id": "credit_card_5694100",
            },
        )
    ]


def test_tau2_retail_source_address_claim_with_tool_name_triggers_correction() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_user_text(
        "Please update my default address and the order address using the luggage "
        "set order address."
    )
    scaffold.observe_tool_output(
        "get_user_details",
        json.dumps({"user_id": "sophia_martin_8570"}),
    )
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W1092119",
                "status": "pending",
                "address": {
                    "address1": "592 Elm Avenue",
                    "address2": "Suite 978",
                    "city": "Houston",
                    "country": "USA",
                    "state": "TX",
                    "zip": "77242",
                },
                "items": [{"name": "Luggage Set", "item_id": "6690069155"}],
            }
        ),
    )
    scaffold.observe_user_text("Yes, please proceed.")

    correction = scaffold.branch_correction_prompt(
        "`modify_user_address` was called for the account/default address."
    )

    assert correction is not None
    assert "modify_user_address" in correction
    assert "CANNOT claim completion" in correction


def test_tau2_retail_contingent_intent_workflow_order_surface() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None

    hint = scaffold.prompt_hint()

    assert "Retail lost-delivered-item continuation scaffold v1" in hint
    assert "pending order cancellation or delivered-item return/exchange" in hint
    assert "inspect known orders" in hint
    assert "Retail turn-economy scaffold v1" in hint
    assert "CANNOT ask the same yes/no confirmation again" in hint
    assert "Retail explicit return completion scaffold v1" in hint
    assert "Retail plural item coverage scaffold v1" in hint
    assert "every observed matching delivered item" in hint


def test_tau2_retail_variant_selection_preserves_wearable_size() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W9911714",
                "status": "pending",
                "items": [
                    {
                        "name": "Running Shoes",
                        "product_id": "6938111410",
                        "item_id": "9791469541",
                        "price": 147.05,
                        "options": {"size": "9", "color": "yellow"},
                    }
                ],
            }
        ),
    )
    scaffold.observe_tool_output(
        "get_product_details",
        json.dumps(
            {
                "name": "Running Shoes",
                "product_id": "6938111410",
                "variants": {
                    "4153505238": {
                        "item_id": "4153505238",
                        "options": {"size": "8", "color": "red"},
                        "available": True,
                        "price": 158.67,
                    },
                    "4107812777": {
                        "item_id": "4107812777",
                        "options": {"size": "9", "color": "black"},
                        "available": True,
                        "price": 155.33,
                    },
                },
            }
        ),
    )

    correction = scaffold.variant_selection_correction_prompt(
        [
            SimpleNamespace(
                name="modify_pending_order_items",
                arguments={
                    "order_id": "#W9911714",
                    "item_ids": ["9791469541"],
                    "new_item_ids": ["4153505238"],
                    "payment_method_id": "gift_card_4332117",
                },
            )
        ]
    )

    assert correction is not None
    assert "4107812777" in correction
    assert "4153505238" in correction
    assert "preserve size" in correction


def test_tau2_retail_variant_selection_preserves_unspecified_option() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_user_text(
        "For the skateboard, I want it to be 34 inch and custom design, "
        "but I don't know about the deck material."
    )
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W3295833",
                "status": "pending",
                "items": [
                    {
                        "name": "Skateboard",
                        "product_id": "1968349452",
                        "item_id": "5312063289",
                        "price": 195.15,
                        "options": {
                            "deck material": "bamboo",
                            "length": "31 inch",
                            "design": "graphic",
                        },
                    }
                ],
            }
        ),
    )
    scaffold.observe_tool_output(
        "get_product_details",
        json.dumps(
            {
                "name": "Skateboard",
                "product_id": "1968349452",
                "variants": {
                    "9594745976": {
                        "item_id": "9594745976",
                        "options": {
                            "deck material": "plastic",
                            "length": "34 inch",
                            "design": "custom",
                        },
                        "available": True,
                        "price": 184.13,
                    },
                    "6956751343": {
                        "item_id": "6956751343",
                        "options": {
                            "deck material": "bamboo",
                            "length": "34 inch",
                            "design": "custom",
                        },
                        "available": True,
                        "price": 217.06,
                    },
                },
            }
        ),
    )

    correction = scaffold.variant_selection_correction_prompt(
        [
            SimpleNamespace(
                name="modify_pending_order_items",
                arguments={
                    "order_id": "#W3295833",
                    "item_ids": ["5312063289"],
                    "new_item_ids": ["9594745976"],
                    "payment_method_id": "credit_card_3261838",
                },
            )
        ]
    )

    assert correction is not None
    assert "6956751343" in correction
    assert "9594745976" in correction
    assert "deck material='bamboo'" in correction


def test_tau2_retail_variant_selection_preserves_unmentioned_options_for_color() -> None:
    from plugins.benchmark_harness.tau2_workflow_order import build_workflow_order_scaffold

    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_user_text("Please change the pending order item color to red.")
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W4860251",
                "status": "pending",
                "items": [
                    {
                        "name": "Luggage Set",
                        "product_id": "5426915165",
                        "item_id": "5209958006",
                        "price": 514.72,
                        "options": {
                            "piece count": "2-piece",
                            "color": "silver",
                            "material": "hardshell",
                        },
                    }
                ],
            }
        ),
    )
    scaffold.observe_tool_output(
        "get_product_details",
        json.dumps(
            {
                "name": "Luggage Set",
                "product_id": "5426915165",
                "variants": {
                    "9956648681": {
                        "item_id": "9956648681",
                        "options": {
                            "piece count": "4-piece",
                            "color": "red",
                            "material": "hardshell",
                        },
                        "available": True,
                        "price": 452.62,
                    },
                    "8964750292": {
                        "item_id": "8964750292",
                        "options": {
                            "piece count": "2-piece",
                            "color": "red",
                            "material": "hardshell",
                        },
                        "available": True,
                        "price": 532.58,
                    },
                    "7160999700": {
                        "item_id": "7160999700",
                        "options": {
                            "piece count": "2-piece",
                            "color": "red",
                            "material": "softshell",
                        },
                        "available": True,
                        "price": 499.29,
                    },
                },
            }
        ),
    )

    correction = scaffold.variant_selection_correction_prompt(
        [
            SimpleNamespace(
                name="modify_pending_order_items",
                arguments={
                    "order_id": "#W4860251",
                    "item_ids": ["5209958006"],
                    "new_item_ids": ["9956648681"],
                    "payment_method_id": "credit_card_2112420",
                },
            )
        ]
    )

    assert correction is not None
    assert "8964750292" in correction
    assert "9956648681" in correction
    assert "piece count='2-piece'" in correction


def test_tau2_retail_variant_selection_ignores_assistant_induced_option_choice() -> None:
    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_user_text("Please change the pending order item color to red.")
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W4860251",
                "status": "pending",
                "items": [
                    {
                        "name": "Luggage Set",
                        "product_id": "5426915165",
                        "item_id": "5209958006",
                        "price": 514.72,
                        "options": {
                            "piece count": "2-piece",
                            "color": "silver",
                            "material": "hardshell",
                        },
                    }
                ],
            }
        ),
    )
    scaffold.observe_tool_output(
        "get_product_details",
        json.dumps(
            {
                "name": "Luggage Set",
                "product_id": "5426915165",
                "variants": {
                    "8964750292": {
                        "item_id": "8964750292",
                        "options": {
                            "piece count": "2-piece",
                            "color": "red",
                            "material": "hardshell",
                        },
                        "available": True,
                        "price": 532.58,
                    },
                    "7160999700": {
                        "item_id": "7160999700",
                        "options": {
                            "piece count": "2-piece",
                            "color": "red",
                            "material": "softshell",
                        },
                        "available": True,
                        "price": 499.29,
                    },
                },
            }
        ),
    )
    scaffold.observe_user_text("Let's go with option 2, the red softshell one.")

    correction = scaffold.variant_selection_correction_prompt(
        [
            SimpleNamespace(
                name="modify_pending_order_items",
                arguments={
                    "order_id": "#W4860251",
                    "item_ids": ["5209958006"],
                    "new_item_ids": ["7160999700"],
                    "payment_method_id": "credit_card_2112420",
                },
            )
        ]
    )

    assert correction is not None
    assert "8964750292" in correction
    assert "7160999700" in correction
    assert "material='hardshell'" in correction


def test_tau2_retail_pending_item_terminal_write_requires_address_tail_check() -> None:
    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None

    correction = scaffold.pending_item_terminal_write_correction_prompt(
        [
            SimpleNamespace(
                name="modify_pending_order_items",
                arguments={
                    "order_id": "#W4860251",
                    "item_ids": ["5209958006"],
                    "new_item_ids": ["8964750292"],
                    "payment_method_id": "credit_card_2112420",
                },
            )
        ]
    )

    assert correction is not None
    assert "#W4860251" in correction
    assert "modify_pending_order_address before modify_pending_order_items" in correction
    assert "CANNOT call modify_pending_order_items first" in correction


def test_tau2_retail_pending_item_terminal_write_allows_after_address_write() -> None:
    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_outgoing_tool_calls(
        [
            SimpleNamespace(
                name="modify_pending_order_address",
                arguments={
                    "order_id": "#W4860251",
                    "address1": "1 Main St",
                    "address2": "",
                    "city": "Chicago",
                    "state": "IL",
                    "country": "USA",
                    "zip": "60601",
                },
            )
        ]
    )

    correction = scaffold.pending_item_terminal_write_correction_prompt(
        [
            SimpleNamespace(
                name="modify_pending_order_items",
                arguments={
                    "order_id": "#W4860251",
                    "item_ids": ["5209958006"],
                    "new_item_ids": ["8964750292"],
                    "payment_method_id": "credit_card_2112420",
                },
            )
        ]
    )

    assert correction is None


def test_tau2_retail_pending_item_terminal_write_allows_same_turn_address_first() -> None:
    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None

    correction = scaffold.pending_item_terminal_write_correction_prompt(
        [
            SimpleNamespace(
                name="modify_pending_order_address",
                arguments={
                    "order_id": "#W4860251",
                    "address1": "1 Main St",
                    "address2": "",
                    "city": "Chicago",
                    "state": "IL",
                    "country": "USA",
                    "zip": "60601",
                },
            ),
            SimpleNamespace(
                name="modify_pending_order_items",
                arguments={
                    "order_id": "#W4860251",
                    "item_ids": ["5209958006"],
                    "new_item_ids": ["8964750292"],
                    "payment_method_id": "credit_card_2112420",
                },
            ),
        ]
    )

    assert correction is None


def test_tau2_retail_cancelled_order_tracking_uses_observed_tracking() -> None:
    scaffold = build_workflow_order_scaffold("retail-contingent-intent-v1")
    assert scaffold is not None
    scaffold.observe_tool_output(
        "get_order_details",
        json.dumps(
            {
                "order_id": "#W1154986",
                "status": "cancelled",
                "fulfillments": [
                    {
                        "tracking_id": ["286422338955"],
                    }
                ],
            }
        ),
    )
    scaffold.observe_user_text("Can you give me the tracking number for my cancelled order?")

    response = scaffold.cancelled_order_tracking_response()

    assert response == "The tracking number for cancelled order #W1154986 is 286422338955."
    scaffold.mark_cancelled_order_tracking_sent()
    assert scaffold.cancelled_order_tracking_response() is None


def test_tau2_drops_premature_transfer_from_read_bundle() -> None:
    corrections: list[str] = []
    calls = [
        SimpleNamespace(name="get_order_details"),
        SimpleNamespace(name="transfer_to_human_agents"),
    ]

    projected = _drop_premature_transfer_from_read_bundle(
        calls,
        branch_corrections=corrections,
    )

    assert [call.name for call in projected] == ["get_order_details"]
    assert corrections == ["premature_transfer_bundle"]


def test_tau2_dedupes_duplicate_projected_tool_calls() -> None:
    corrections: list[str] = []
    calls = [
        SimpleNamespace(
            name="return_delivered_order_items",
            arguments={
                "order_id": "#W7449508",
                "item_ids": ["6477915553"],
                "payment_method_id": "gift_card_7711863",
            },
        ),
        SimpleNamespace(
            name="return_delivered_order_items",
            arguments={
                "order_id": "#W7449508",
                "item_ids": ["6477915553"],
                "payment_method_id": "gift_card_7711863",
            },
        ),
    ]

    projected = _dedupe_duplicate_tool_calls(calls, branch_corrections=corrections)

    assert projected == [calls[0]]
    assert corrections == ["duplicate_tool_call_dedupe"]


def test_tau2_agent_planner_loads_telecom_mms_sequence() -> None:
    planner_id, planner_text = _load_agent_planner("telecom-mms-v1")

    assert planner_id == "telecom-mms-v1"
    assert "Telecom MMS deterministic planner candidate v1" in planner_text
    assert "toggle_airplane_mode" in planner_text
    assert "reseat_sim_card" in planner_text
    assert "toggle_data" in planner_text
    assert "set_network_mode_preference" in planner_text
    assert "reset_apn_settings" in planner_text
    assert "can_send_mms" in planner_text
    assert planner_text.index("reset_apn_settings") < planner_text.index("can_send_mms")


def test_tau2_agent_candidate_surface_combines_guard_and_planner() -> None:
    candidate_id, candidate_text = _compose_agent_candidate_surface(
        agent_guard="t1",
        guard_text="T1 guard text",
        agent_planner="telecom-mms-v1",
        planner_text="Planner text",
    )

    assert candidate_id == "t1+telecom-mms-v1"
    assert candidate_text == "T1 guard text\n\nPlanner text"


def test_retail_write_preflight_rejects_delivered_exchange_on_pending_order() -> None:
    preflight = RetailWritePreflight.empty()
    preflight.observe_tool_output(
        {
            "order_id": "#W7464385",
            "status": "pending",
            "items": [{"item_id": "1810466394"}],
            "payment_history": [{"payment_method_id": "paypal_1261484"}],
        }
    )

    violations = preflight.validate_tool_calls(
        [
            SimpleNamespace(
                name="exchange_delivered_order_items",
                arguments={
                    "order_id": "#W7464385",
                    "item_ids": ["1810466394"],
                    "new_item_ids": ["6700049080"],
                    "payment_method_id": "paypal_1261484",
                },
            )
        ]
    )

    assert violations == [
        "exchange_delivered_order_items(#W7464385) requires delivered status, observed 'pending'."
    ]
    assert "Retail write preflight blocked" in preflight.correction_prompt(violations)


def test_retail_write_preflight_unknown_order_requires_detail_lookup() -> None:
    preflight = RetailWritePreflight.empty()
    preflight.observe_tool_output(
        json.dumps(
            {
                "user_id": "olivia_lopez_3865",
                "payment_methods": {"gift_card_7711863": {"source": "gift_card"}},
                "orders": ["#W5481803"],
            }
        )
    )

    violations = preflight.validate_tool_calls(
        [
            SimpleNamespace(
                name="cancel_pending_order",
                arguments={"order_id": "#W5481803", "reason": "no longer needed"},
            )
        ]
    )

    assert violations == ["cancel_pending_order(#W5481803) has no observed order details."]
    correction = preflight.correction_prompt(violations)
    assert "get_order_details" in correction
    assert "CANNOT cancel" in correction


def test_retail_write_preflight_allows_pending_item_modification() -> None:
    preflight = RetailWritePreflight.empty()
    preflight.observe_tool_output(
        json.dumps(
            {
                "order_id": "#W7464385",
                "status": "pending",
                "items": [{"item_id": "1810466394"}],
                "payment_history": [{"payment_method_id": "paypal_1261484"}],
            }
        )
    )

    violations = preflight.validate_tool_calls(
        [
            SimpleNamespace(
                name="modify_pending_order_items",
                arguments={
                    "order_id": "#W7464385",
                    "item_ids": ["1810466394"],
                    "new_item_ids": ["6117189161"],
                    "payment_method_id": "paypal_1261484",
                },
            )
        ]
    )

    assert violations == []


def test_retail_write_preflight_tracks_pending_address_update() -> None:
    preflight = RetailWritePreflight.empty()
    preflight.observe_tool_output(
        {
            "order_id": "#W2702727",
            "status": "pending",
            "items": [{"item_id": "7373893106"}],
            "payment_history": [{"payment_method_id": "credit_card_3599838"}],
        }
    )

    violations = preflight.validate_tool_calls(
        [
            SimpleNamespace(
                name="modify_pending_order_address",
                arguments={
                    "order_id": "#W2702727",
                    "address1": "1234 Elm St",
                    "address2": "",
                    "city": "Springfield",
                    "state": "IL",
                    "country": "USA",
                    "zip": "62701",
                },
            )
        ]
    )

    assert violations == []


@pytest.mark.parametrize(
    ("tool_name", "base_input"),
    [
        (
            "modify_pending_order_address",
            {
                "order_id": "#W2702727",
                "address1": "1234 Elm St",
                "address2": "",
                "city": "Springfield",
                "state": "IL",
                "country": "USA",
                "zip": "62701",
            },
        ),
        (
            "modify_user_address",
            {
                "user_id": "ethan_garcia_1261",
                "address1": "101 Highway",
                "city": "New York",
                "state": "NY",
                "country": "USA",
                "zip": "10001",
            },
        ),
    ],
)
def test_tau2_tool_calls_preserves_empty_address2_for_retail_address_update(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    base_input: dict[str, str],
) -> None:
    fake_tau2 = ModuleType("tau2")
    fake_data_model = ModuleType("tau2.data_model")
    fake_message = ModuleType("tau2.data_model.message")
    fake_message.ToolCall = SimpleNamespace
    monkeypatch.setitem(sys.modules, "tau2", fake_tau2)
    monkeypatch.setitem(sys.modules, "tau2.data_model", fake_data_model)
    monkeypatch.setitem(sys.modules, "tau2.data_model.message", fake_message)

    result = SimpleNamespace(
        tool_calls=[
            {
                "tool_use_id": "call_1",
                "tool": tool_name,
                "input": base_input,
                "result": None,
            }
        ]
    )

    calls = _tau2_tool_calls(result, requestor="assistant")

    assert len(calls) == 1
    assert calls[0].arguments["address2"] == ""


def test_telecom_workflow_order_delays_terminal_verifier() -> None:
    scaffold = TelecomMmsWorkflowOrder()

    assert scaffold.premature_terminal_tool("can_send_mms") is True
    assert "can_send_mms as the terminal verifier" in scaffold.prompt_hint()
    assert "airplane_mode_off" in scaffold.prompt_hint()


def test_telecom_workflow_order_tracks_blocker_outputs() -> None:
    scaffold = TelecomMmsWorkflowOrder()

    scaffold.observe_tool_output(
        "check_network_status",
        (
            "Airplane Mode: ON\n"
            "SIM Card Status: missing\n"
            "Cellular Network Type: 2G\n"
            "Mobile Data Enabled: No"
        ),
    )
    assert scaffold.airplane_off is False
    assert scaffold.sim_active is False
    assert scaffold.mobile_data_on is False
    assert scaffold.non_2g_network is False
    assert scaffold.premature_terminal_tool("can_send_mms") is True

    scaffold.observe_tool_output("toggle_airplane_mode", "Airplane Mode is now OFF.")
    scaffold.observe_tool_output("reseat_sim_card", "SIM card re-seated successfully.")
    scaffold.observe_tool_output("toggle_data", "Mobile data is now on.")
    scaffold.observe_tool_output("set_network_mode_preference", "Network Type: 4G")
    scaffold.observe_tool_output("reset_apn_settings", "MMSC URL: http://mms.example")

    assert scaffold.blockers_clear() is True
    assert scaffold.premature_terminal_tool("can_send_mms") is False
    scaffold.account_roaming_enabled = False
    assert scaffold.premature_terminal_tool("can_send_mms") is True


def test_telecom_workflow_order_projects_diagnostic_user_action_bundle() -> None:
    scaffold = TelecomMmsWorkflowOrder()

    assert scaffold.projected_user_tool_actions() == [("check_network_status", {})]

    scaffold.observe_tool_output(
        "check_network_status",
        (
            "Airplane Mode: ON\n"
            "SIM Card Status: missing\n"
            "Cellular Network Type: 2G\n"
            "Mobile Data Enabled: No\n"
            "Data Roaming Enabled: No"
        ),
    )

    assert scaffold.projected_user_tool_actions() == [
        ("toggle_airplane_mode", {}),
        ("reseat_sim_card", {}),
        ("toggle_data", {}),
        ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
        ("reset_apn_settings", {}),
        ("reboot_device", {}),
        ("check_apn_settings", {}),
    ]
    scaffold.mark_projected_user_tool_actions(
        [
            ("toggle_airplane_mode", {}),
            ("reseat_sim_card", {}),
            ("toggle_data", {}),
            ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
            ("reset_apn_settings", {}),
            ("reboot_device", {}),
            ("check_apn_settings", {}),
        ]
    )
    assert scaffold.projected_user_tool_actions() == []

    scaffold.observe_tool_output("toggle_airplane_mode", "Airplane Mode is now OFF.")
    scaffold.observe_tool_output("reseat_sim_card", "SIM card re-seated successfully.")
    scaffold.observe_tool_output("toggle_data", "Mobile data is now on.")
    scaffold.observe_tool_output("set_network_mode_preference", "Network Type: 5G")
    scaffold.observe_tool_output("check_apn_settings", "MMSC URL: http://mms.example")

    assert scaffold.projected_user_tool_actions() == [("toggle_roaming", {})]

    scaffold.observe_tool_output("toggle_roaming", "Data roaming is now ON.")

    assert scaffold.projected_user_tool_actions() == [("can_send_mms", {})]
    scaffold.mark_projected_user_tool_actions([("can_send_mms", {})])
    assert scaffold.projected_user_tool_actions() == []


def test_telecom_workflow_order_observes_direct_tool_message() -> None:
    scaffold = TelecomMmsWorkflowOrder()

    scaffold.observe_incoming_message(
        SimpleNamespace(
            role="tool",
            content=(
                "Airplane Mode: ON\n"
                "SIM Card Status: missing\n"
                "Cellular Network Type: 2G\n"
                "Mobile Data Enabled: No"
            ),
        )
    )

    assert scaffold.airplane_off is False
    assert scaffold.sim_active is False
    assert scaffold.mobile_data_on is False
    assert scaffold.non_2g_network is False


def test_telecom_workflow_order_observes_enum_tool_role() -> None:
    scaffold = TelecomMmsWorkflowOrder()

    scaffold.observe_incoming_message(
        SimpleNamespace(
            role=SimpleNamespace(value="tool"),
            content=(
                "Airplane Mode: OFF\n"
                "SIM Card Status: active\n"
                "Cellular Network Type: 5G\n"
                "Mobile Data Enabled: Yes"
            ),
        )
    )

    assert scaffold.airplane_off is True
    assert scaffold.sim_active is True
    assert scaffold.mobile_data_on is True
    assert scaffold.non_2g_network is True


def test_telecom_workflow_order_observes_dict_tool_message() -> None:
    scaffold = TelecomMmsWorkflowOrder()

    scaffold.observe_incoming_message(
        {
            "role": "tool",
            "content": ("Airplane Mode is now OFF.\nStatus Bar: Excellent | 5G | Data Disabled"),
        }
    )

    assert scaffold.airplane_off is True


def test_telecom_workflow_order_corrects_test_sending_before_roaming_repair() -> None:
    scaffold = TelecomMmsWorkflowOrder(
        step_economy=True,
        bounded_bundle=True,
        roaming_recovery=True,
        late_stage_compression=True,
    )
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = False

    correction = scaffold.branch_correction_prompt(
        "Please test sending an MMS now and tell me whether it succeeds."
    )

    assert correction is not None
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in correction


def test_telecom_workflow_order_requires_line_detail_before_terminal() -> None:
    scaffold = TelecomMmsWorkflowOrder(
        step_economy=True,
        bounded_bundle=True,
        roaming_recovery=True,
        late_stage_compression=True,
    )
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.observe_tool_output(
        "get_customer_by_phone",
        {
            "customer_id": "C1001",
            "phone_number": "555-123-2002",
            "line_ids": ["L1001", "L1002"],
        },
    )

    assert scaffold.line_detail_lookup_due() is True
    hint = scaffold.prompt_hint()
    assert "Line-detail lookup protocol v1" in hint
    assert "get_details_by_id" in hint
    correction = scaffold.branch_correction_prompt("Please run can_send_mms now.")
    assert correction is not None
    assert "L1001, L1002" in correction


def test_telecom_step_economy_scaffold_recommends_safe_bundle() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-step-economy-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.step_economy is True
    assert scaffold.bounded_bundle is False
    hint = scaffold.prompt_hint()
    assert "Step-economy scaffold v1" in hint
    assert "toggle_airplane_mode" in hint
    assert "reseat_sim_card" in hint
    assert "toggle_data" in hint
    assert "Keep can_send_mms out of the bundle" in hint


def test_telecom_bounded_bundle_scaffold_limits_user_actions() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-bounded-bundle-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.step_economy is True
    assert scaffold.bounded_bundle is True
    hint = scaffold.prompt_hint()
    assert "Bounded bundle protocol v1" in hint
    assert "The bundle allowlist is exactly" in hint
    assert "Exclude can_send_mms" in hint
    assert "roaming" in hint
    assert "separate can_send_mms terminal verification" in hint


def test_telecom_roaming_recovery_scaffold_opens_after_failed_terminal_mms() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-roaming-recovery-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.roaming_recovery is True
    scaffold.observe_tool_output("toggle_airplane_mode", "Airplane Mode is now OFF.")
    scaffold.observe_tool_output("reseat_sim_card", "SIM card re-seated successfully.")
    scaffold.observe_tool_output("toggle_data", "Mobile data is now on.")
    scaffold.observe_tool_output("set_network_mode_preference", "Network Type: 4G")
    scaffold.observe_tool_output("reset_apn_settings", "MMSC URL: http://mms.example")
    scaffold.observe_tool_output("can_send_mms", "Your messaging app cannot send MMS messages.")

    hint = scaffold.prompt_hint()
    assert "Account identity protocol v1" in hint
    assert "get_customer_by_phone" in hint

    scaffold.observe_tool_output(
        "get_customer_by_phone",
        {
            "customer_id": "C1001",
            "phone_number": "555-123-2002",
            "line_ids": ["L1002"],
        },
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        {"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": False},
    )
    hint = scaffold.prompt_hint()
    assert "Roaming recovery protocol v1" in hint
    assert "enable_roaming" in hint
    assert "turn_roaming_on" in hint
    assert "Before terminal can_send_mms" in hint


def test_telecom_roaming_recovery_blocks_wifi_branch_until_roaming_repaired() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-roaming-recovery-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "get_customer_by_phone",
        '{"customer_id": "C1001", "phone_number": "555-123-2002"}',
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}',
    )
    scaffold.observe_tool_output("toggle_airplane_mode", "Airplane Mode is now OFF.")
    scaffold.observe_tool_output("reseat_sim_card", "SIM card re-seated successfully.")
    scaffold.observe_tool_output("toggle_data", "Mobile data is now on.")
    scaffold.observe_tool_output("set_network_mode_preference", "Network Type: 4G")
    scaffold.observe_tool_output("reset_apn_settings", "MMSC URL: http://mms.example")
    scaffold.observe_tool_output("can_send_mms", "Your messaging app cannot send MMS messages.")

    correction = scaffold.branch_correction_prompt(
        "Next, please check Wi-Fi Calling and messaging app permissions."
    )

    assert correction is not None
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in correction
    assert "Do not ask about Wi-Fi calling" in correction


def test_telecom_roaming_recovery_repairs_known_roaming_before_terminal_mms() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-roaming-recovery-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "get_customer_by_phone",
        '{"customer_id": "C1001", "phone_number": "555-123-2002"}',
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}',
    )
    scaffold.observe_tool_output("toggle_airplane_mode", "Airplane Mode is now OFF.")
    scaffold.observe_tool_output("reseat_sim_card", "SIM card re-seated successfully.")
    scaffold.observe_tool_output("toggle_data", "Mobile data is now on.")
    scaffold.observe_tool_output("set_network_mode_preference", "Network Type: 4G")
    scaffold.observe_tool_output("reset_apn_settings", "MMSC URL: http://mms.example")

    hint = scaffold.prompt_hint()
    correction = scaffold.branch_correction_prompt(
        "Great — the prerequisites are clear now. Please run the MMS send check now."
    )

    assert scaffold.roaming_repair_due() is True
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in hint
    assert "Before terminal can_send_mms" in hint
    assert correction is not None
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in correction


def test_telecom_roaming_recovery_repairs_known_account_blocker_after_state_reset() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "get_customer_by_phone",
        '{"customer_id": "C1001", "phone_number": "555-123-2002"}',
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}',
    )

    correction = scaffold.branch_correction_prompt(
        "The affected line is active. Please reboot the phone and try MMS again."
    )

    assert scaffold.known_account_roaming_repair_due() is True
    assert correction is not None
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in correction


def test_telecom_proactive_roaming_repairs_account_before_apn_only_followup() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-proactive-roaming-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.proactive_roaming is True
    scaffold.observe_tool_output(
        "get_customer_by_phone",
        '{"customer_id": "C1001", "phone_number": "555-123-2002"}',
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}',
    )
    scaffold.observe_tool_output(
        "",
        "Airplane Mode: OFF\n"
        "SIM Card Status: active\n"
        "Cellular Network Type: 5G\n"
        "Mobile Data Enabled: Yes\n"
        "Data Roaming Enabled: No",
    )

    hint = scaffold.prompt_hint()
    correction = scaffold.branch_correction_prompt(
        "Before trying the MMS send test, please run check_apn_settings and confirm MMSC URL."
    )

    assert scaffold.account_roaming_repair_due() is True
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in hint
    assert "Before terminal can_send_mms" in hint
    assert correction is not None
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in correction


def test_telecom_late_compression_combines_apn_roaming_and_terminal_followup() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.late_stage_compression is True
    assert scaffold.proactive_roaming is False
    scaffold.observe_tool_output(
        "get_customer_by_phone",
        '{"customer_id": "C1001", "phone_number": "555-123-2002"}',
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}',
    )

    early_hint = scaffold.prompt_hint()
    assert scaffold.late_stage_compression_due() is False
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' not in early_hint

    scaffold.observe_tool_output(
        "",
        "Airplane Mode: OFF\n"
        "SIM Card Status: active\n"
        "Cellular Network Type: 5G\n"
        "Mobile Data Enabled: Yes\n"
        "Data Roaming Enabled: No",
    )

    hint = scaffold.prompt_hint()
    correction = scaffold.branch_correction_prompt(
        "Please run check_apn_settings first, then we can try sending MMS."
    )

    assert scaffold.late_stage_compression_due() is True
    assert "Late-stage compression protocol v1" in hint
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in hint
    assert "check_apn_settings; turn_roaming_on or toggle_roaming; can_send_mms" in hint
    assert correction is not None
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in correction


def test_telecom_late_compression_corrects_phone_bundle_after_roaming_false() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "get_customer_by_phone",
        '{"customer_id": "C1001", "phone_number": "555-123-2002"}',
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}',
    )
    scaffold.observe_tool_output(
        "",
        "Airplane Mode: OFF\n"
        "SIM Card Status: active\n"
        "Cellular Network Type: 5G\n"
        "Mobile Data Enabled: Yes\n"
        "Data Roaming Enabled: No",
    )
    scaffold.observe_tool_output("check_apn_settings", "MMSC URL: http://mms.example")

    correction = scaffold.branch_correction_prompt(
        "Next, please complete this one bundle: reboot the phone and then report whether the "
        "MMS issue is fixed."
    )

    assert correction is not None
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in correction


def test_tau2_agent_observes_geode_read_tool_outputs_for_workflow_state() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    _observe_workflow_result_tool_outputs(
        SimpleNamespace(
            tool_calls=[
                {
                    "tool": "get_customer_by_phone",
                    "result": {
                        "result": (
                            '{"customer_id": "C1001", "phone_number": "555-123-2002", '
                            '"line_ids": ["L1001", "L1002"]}'
                        )
                    },
                },
                {
                    "tool": "get_details_by_id",
                    "result": {
                        "output": (
                            '{"line_id": "L1002", "phone_number": "555-123-2002", '
                            '"roaming_enabled": false}'
                        )
                    },
                },
            ]
        ),
        scaffold,
    )

    assert scaffold.active_customer_id == "C1001"
    assert scaffold.active_phone_number == "555-123-2002"
    assert scaffold.active_line_id == "L1002"
    assert scaffold.account_roaming_enabled is False


def test_tau2_agent_hydrates_workflow_order_from_message_history() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    history = [
        {
            "role": "tool",
            "content": (
                "Airplane Mode: OFF\n"
                "SIM Card Status: active\n"
                "Cellular Network Type: 5G\n"
                "Mobile Data Enabled: Yes\n"
                "Data Roaming Enabled: No"
            ),
        },
        {
            "role": "tool",
            "content": (
                '{"customer_id": "C1001", "phone_number": "555-123-2002", '
                '"line_ids": ["L1001", "L1002"]}'
            ),
        },
        {
            "role": "tool",
            "content": (
                '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}'
            ),
        },
        {
            "role": "tool",
            "content": "Current APN Name: internet\nMMSC URL: http://mms.example",
        },
    ]

    _hydrate_workflow_order_from_history(scaffold, history)

    correction = scaffold.branch_correction_prompt("Please reboot the device first.")
    assert correction is not None
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in correction


def test_tau2_agent_projects_account_roaming_repair_from_workflow_state() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = False

    assert _project_account_roaming_repair_from_workflow_order(scaffold) == (
        "C1001",
        "L1002",
    )


def test_telecom_workflow_order_corrects_repeated_network_diagnostic_after_known_blockers() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "check_network_status",
        (
            "Airplane Mode: ON\n"
            "SIM Card Status: missing\n"
            "Cellular Network Type: none\n"
            "Mobile Data Enabled: No\n"
            "Data Roaming Enabled: No"
        ),
    )

    correction = scaffold.branch_correction_prompt(
        "Please run check_network_status again and send me the result."
    )

    assert correction is not None
    assert "known repair action" in correction
    assert "toggle_airplane_mode" in correction
    assert "toggle_data" in correction


def test_telecom_workflow_order_corrects_redundant_check_before_known_repair() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = False
    scaffold.mobile_data_on = False
    scaffold.non_2g_network = False
    scaffold.apn_valid = False

    correction = scaffold.branch_correction_prompt(
        "Please check_sim_status first. If it is missing, reseat the SIM. "
        "Then check_network_status before changing mobile data."
    )

    assert correction is not None
    assert "redundant check" in correction
    assert "reseat_sim_card" in correction
    assert "toggle_data" in correction
    assert "confirmatory re-check" in correction


def test_telecom_late_compression_prompts_repair_only_bundle_for_known_false_blockers() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = False
    scaffold.sim_active = False
    scaffold.mobile_data_on = False
    scaffold.non_2g_network = False
    scaffold.apn_valid = False

    hint = scaffold.prompt_hint()

    assert "Native repair-only compression rule" in hint
    assert "do not ask for check_network_status" in hint
    assert "toggle_airplane_mode" in hint
    assert "reseat_sim_card" in hint
    assert "toggle_data" in hint
    assert 'set_network_mode_preference(mode="4g_5g_preferred")' in hint
    assert "reset_apn_settings" in hint
    assert "reboot_device" in hint
    assert "check_apn_settings" in hint


def test_telecom_late_compression_prompts_single_probe_for_unknown_phone_state() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    hint = scaffold.prompt_hint()

    assert "Native initial phone-state probe rule" in hint
    assert "exactly one diagnostic tool action: check_network_status" in hint
    assert "do not ask for a broad manual checklist" in hint
    assert "repair-only compression rule" in hint


def test_telecom_late_compression_inspects_active_line_before_phone_probe() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.candidate_line_ids = ["L1001", "L1002"]

    assert scaffold.line_detail_lookup_due() is True
    hint = scaffold.prompt_hint()
    assert "Line-detail lookup protocol v1" in hint
    assert "get_details_by_id" in hint
    assert "Native initial phone-state probe rule" not in hint


def test_tau2_agent_projects_line_detail_lookup_from_workflow_state() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.candidate_line_ids = ["L1001", "L1002", "L1003"]

    assert _project_line_detail_lookup_from_workflow_order(scaffold) == ["L1002"]


def test_tau2_agent_falls_back_to_all_line_details_without_unique_phone_suffix() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.candidate_line_ids = ["L1002", "L2002"]

    assert _project_line_detail_lookup_from_workflow_order(scaffold) == [
        "L1002",
        "L2002",
    ]


def test_tau2_agent_does_not_repeat_projected_line_detail_lookup() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.candidate_line_ids = ["L1001", "L1002", "L1003"]
    scaffold.mark_projected_line_detail_lookups(["L1001", "L1002", "L1003"])

    assert _project_line_detail_lookup_from_workflow_order(scaffold) == []


def test_telecom_workflow_order_tracks_projected_line_detail_tool_results() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_customer_id = "C1001"
    scaffold.observe_outgoing_tool_calls(
        [
            SimpleNamespace(name="get_details_by_id"),
            SimpleNamespace(name="get_details_by_id"),
        ]
    )

    scaffold.observe_tool_output(
        "",
        '{"line_id": "L1001", "phone_number": "555-123-2001", "roaming_enabled": false}',
    )
    scaffold.observe_tool_output(
        "",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}',
    )

    assert scaffold.active_line_id == "L1002"
    assert scaffold.account_roaming_enabled is False
    assert scaffold.known_account_roaming_repair_due() is True


def test_telecom_workflow_order_ignores_roaming_state_for_non_active_line() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.active_phone_number = "555-123-2002"
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": true}',
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1003", "phone_number": "555-123-2003", "roaming_enabled": false}',
    )

    assert scaffold.active_line_id == "L1002"
    assert scaffold.account_roaming_enabled is True


def test_tau2_agent_projects_account_identity_lookup_from_known_phone() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.active_phone_number = "555-123-2002"

    assert _project_account_identity_lookup_from_workflow_order(scaffold) == "555-123-2002"


def test_tau2_user_identity_projection_carries_phone_side_status() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True

    text = _projected_user_identity_text("555-123-2002", scaffold)
    receiving_scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(receiving_scaffold, TelecomMmsWorkflowOrder)
    receiving_scaffold.observe_user_text(text)

    assert "555-123-2002" in text
    assert receiving_scaffold.active_phone_number == "555-123-2002"
    assert receiving_scaffold.blockers_clear() is True
    assert receiving_scaffold.device_roaming_on is True


def test_tau2_user_projector_extracts_phone_number_from_instructions() -> None:
    instructions = (
        "You are John Smith. The affected mobile line is 555-123-2002. You need help with MMS."
    )

    assert _project_phone_number_from_user_instructions(instructions) == "555-123-2002"


def test_tau2_user_projector_extracts_phone_number_from_structured_instructions() -> None:
    instructions = {
        "domain": "telecom",
        "known_info": "You are John Smith with phone number 555-123-2002.",
        "task_instructions": [
            "Ground device status on tool calls.",
            {"location": "France"},
        ],
    }

    assert _project_phone_number_from_user_instructions(instructions) == "555-123-2002"


def test_tau2_user_projector_extracts_phone_number_from_object_instructions() -> None:
    class ScenarioInstructions:
        known_info = "You are John Smith with phone number 555-123-2002."

        def __str__(self) -> str:
            return f"ScenarioInstructions(known_info={self.known_info!r})"

    assert _project_phone_number_from_user_instructions(ScenarioInstructions()) == "555-123-2002"


def test_tau2_user_projector_extracts_phone_number_from_model_dump() -> None:
    class ScenarioInstructions:
        def model_dump(self) -> dict[str, str]:
            return {"known_info": "You are John Smith with phone number 555-123-2002."}

    assert _project_phone_number_from_user_instructions(ScenarioInstructions()) == "555-123-2002"


def test_tau2_agent_projects_account_roaming_repair_from_prompt() -> None:
    prompt = (
        "Tool result to assistant agent from tau2 orchestrator:\n"
        '{"customer_id": "C1001", "phone_number": "555-123-2002"}\n'
        '{"line_id": "L1001", "phone_number": "555-123-2001", '
        '"roaming_enabled": false}\n'
        '{"line_id": "L1002", "phone_number": "555-123-2002", '
        '"roaming_enabled": false}'
    )

    assert _project_account_roaming_repair_from_prompt(prompt) == ("C1001", "L1002")


def test_tau2_agent_projects_account_roaming_repair_from_escaped_prompt() -> None:
    prompt = (
        "Tool results to assistant agent from tau2 orchestrator:\\n"
        '{\\"customer_id\\": \\"C1001\\", \\"phone_number\\": \\"555-123-2002\\"}\\n'
        '{\\"line_id\\": \\"L1002\\", \\"phone_number\\": \\"555-123-2002\\", '
        '\\"roaming_enabled\\": false}'
    )

    assert _project_account_roaming_repair_from_prompt(prompt) == ("C1001", "L1002")


def test_telecom_workflow_order_tracks_user_tool_outputs_without_names() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-roaming-recovery-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "get_customer_by_phone",
        '{"customer_id": "C1001", "phone_number": "555-123-2002"}',
    )
    scaffold.observe_tool_output(
        "get_details_by_id",
        '{"line_id": "L1002", "phone_number": "555-123-2002", "roaming_enabled": false}',
    )
    scaffold.observe_tool_output(
        "",
        "Airplane Mode: OFF\n"
        "SIM Card Status: active\n"
        "Cellular Network Type: 5G\n"
        "Mobile Data Enabled: Yes\n"
        "Data Roaming Enabled: No",
    )
    scaffold.observe_tool_output(
        "",
        "Current APN Name: internet\n"
        "MMSC URL (for picture messages): http://mms.carrier.com/mms/wapenc",
    )
    scaffold.observe_tool_output("", "Your messaging app cannot send MMS messages.")

    assert scaffold.blockers_clear() is True
    assert scaffold.mms_failed_after_prereqs is True
    assert scaffold.roaming_repair_due() is True
    assert 'enable_roaming(customer_id="C1001", line_id="L1002")' in scaffold.prompt_hint()


def test_telecom_user_projector_turns_phone_roaming_on_after_account_repair() -> None:
    scaffold = TelecomMmsWorkflowOrder()
    scaffold.observe_tool_output(
        "",
        "Airplane Mode: OFF\n"
        "SIM Card Status: active\n"
        "Cellular Network Type: 5G\n"
        "Mobile Data Enabled: Yes\n"
        "Data Roaming Enabled: No",
    )
    scaffold.observe_tool_output(
        "",
        "Current APN Name: internet\n"
        "MMSC URL (for picture messages): http://mms.carrier.com/mms/wapenc",
    )
    scaffold.observe_tool_output("", "Roaming enabled successfully")

    assert scaffold.account_roaming_enabled is True
    assert scaffold.device_roaming_on is False
    assert scaffold.projected_user_tool_actions() == [("toggle_roaming", {})]


def test_telecom_user_projector_includes_phone_roaming_in_prereq_bundle() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "",
        "Airplane Mode: OFF\n"
        "SIM Card Status: active\n"
        "Cellular Network Type: 5G\n"
        "Mobile Data Enabled: Yes\n"
        "Data Roaming Enabled: No",
    )
    scaffold.observe_tool_output(
        "",
        "Current APN Name: internet\n"
        "MMSC URL (for picture messages): http://mms.carrier.com/mms/wapenc",
    )

    assert ("toggle_roaming", {}) in scaffold.projected_user_tool_actions()


def test_telecom_workflow_order_requires_account_identity_before_terminal_mms() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True

    assert scaffold.account_identity_lookup_due() is True
    assert "Account identity protocol v1" in scaffold.prompt_hint()
    correction = scaffold.branch_correction_prompt("Please try sending MMS now.")
    assert correction is not None
    assert "get_customer_by_phone" in correction


def test_telecom_user_projector_does_not_terminal_verify_before_account_identity() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True

    assert scaffold.account_identity_lookup_due() is True
    assert scaffold.projected_user_tool_actions() == []


def test_telecom_user_projector_marks_projected_bundle_as_clear_state() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mark_projected_user_tool_actions(
        [
            ("toggle_airplane_mode", {}),
            ("reseat_sim_card", {}),
            ("toggle_data", {}),
            ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
            ("check_apn_settings", {}),
            ("toggle_roaming", {}),
        ]
    )

    assert scaffold.blockers_clear() is True
    assert scaffold.device_roaming_on is True
    assert scaffold.account_identity_lookup_due() is True
    assert scaffold.projected_user_tool_actions() == []


def test_telecom_user_projector_records_identity_once_and_then_terminal_due() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mark_projected_user_tool_actions(
        [
            ("toggle_airplane_mode", {}),
            ("reseat_sim_card", {}),
            ("toggle_data", {}),
            ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
            ("check_apn_settings", {}),
            ("toggle_roaming", {}),
        ]
    )
    scaffold.mark_projected_user_identity("555-123-2002")

    assert scaffold.projected_identity_phone_sent is True
    assert scaffold.active_phone_number == "555-123-2002"
    assert scaffold.account_identity_lookup_due() is True
    assert scaffold.terminal_mms_projection_due() is False

    scaffold.account_roaming_enabled = True

    assert scaffold.terminal_mms_projection_due() is True


def test_telecom_user_projector_reopens_terminal_verify_after_account_repair() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = True

    assert scaffold.projected_user_tool_actions() == [("can_send_mms", {})]


def test_telecom_user_projector_v2_repairs_app_permissions_after_terminal_failure() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v2")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = True
    scaffold.observe_tool_output("can_send_mms", "Your messaging app cannot send MMS messages.")

    assert scaffold.projected_user_tool_actions() == [
        ("check_wifi_calling_status", {}),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "sms"},
        ),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "storage"},
        ),
    ]


def test_telecom_user_projector_v2_toggles_wifi_calling_only_after_observation() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v2")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = True
    scaffold.observe_tool_output("can_send_mms", "Your messaging app cannot send MMS messages.")
    scaffold.observe_tool_output(
        "check_wifi_calling_status",
        "Wi-Fi Calling is currently turned ON.",
    )
    scaffold.mark_projected_user_tool_actions([("check_wifi_calling_status", {})])

    assert ("toggle_wifi_calling", {}) in scaffold.projected_user_tool_actions()


def test_telecom_user_projector_v2_falls_through_to_terminal_after_repairs() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v2")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = True
    scaffold.observe_tool_output("can_send_mms", "Your messaging app cannot send MMS messages.")
    repairs = [
        ("check_wifi_calling_status", {}),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "sms"},
        ),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "storage"},
        ),
    ]
    scaffold.mark_projected_user_tool_actions(repairs)
    scaffold.observe_tool_output(
        "check_wifi_calling_status",
        "Wi-Fi Calling is currently turned OFF.",
    )

    assert scaffold.projected_user_tool_actions() == [("can_send_mms", {})]


def test_telecom_user_projector_dedups_same_tool_by_arguments() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v2")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = True
    scaffold.wifi_calling_safe = True
    scaffold.messaging_sms_permission = False
    scaffold.messaging_storage_permission = False
    scaffold.observe_tool_output("can_send_mms", "Your messaging app cannot send MMS messages.")

    scaffold.mark_projected_user_tool_actions(
        [
            (
                "grant_app_permission",
                {"app_name": "messaging", "permission": "sms"},
            )
        ]
    )

    assert scaffold.projected_user_tool_actions() == [
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "storage"},
        )
    ]


def test_telecom_harness_compression_v3_projects_data_usage_before_terminal() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v3")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = True

    assert scaffold.data_usage_lookup_due() is True
    assert scaffold.terminal_mms_projection_due() is False
    assert scaffold.projected_user_tool_actions() == []
    assert _project_data_usage_lookup_from_workflow_order(scaffold) == ("C1001", "L1002")


def test_telecom_harness_compression_v3_projects_refuel_after_over_limit_usage() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v3")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = True
    scaffold.observe_tool_output(
        "get_data_usage",
        '{"line_id":"L1002","data_used_gb":"15.1","data_limit_gb":"15.0",'
        '"data_refueling_gb":"0.0"}',
    )

    assert scaffold.data_usage_exceeded is True
    assert scaffold.data_usage_lookup_due() is False
    assert scaffold.data_refuel_due() is True
    assert scaffold.terminal_mms_projection_due() is False
    assert _project_data_refuel_from_workflow_order(scaffold) == ("C1001", "L1002", 2.0)

    scaffold.observe_tool_output(
        "refuel_data",
        '{"message":"Successfully added 2.0 GB of data for line L1002 for $4.00",'
        '"new_data_refueling_gb":2.0,"charge":4.0}',
    )

    assert scaffold.data_refueled is True
    assert scaffold.data_refuel_due() is False
    assert scaffold.terminal_mms_projection_due() is True


def test_telecom_user_projector_reads_assistant_account_repair_confirmation() -> None:
    scaffold = TelecomMmsWorkflowOrder()
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True

    scaffold.observe_incoming_message(
        {
            "role": "assistant",
            "content": "Roaming is enabled on the line now. Please try MMS again.",
        }
    )

    assert scaffold.account_roaming_enabled is True
    assert scaffold.projected_user_tool_actions() == [("toggle_roaming", {})]


def test_telecom_user_projector_reads_assistant_account_repair_now_enabled() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mark_projected_user_tool_actions(
        [
            ("toggle_airplane_mode", {}),
            ("reseat_sim_card", {}),
            ("toggle_data", {}),
            ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
            ("check_apn_settings", {}),
            ("toggle_roaming", {}),
        ]
    )
    scaffold.observe_incoming_message(
        {
            "role": "assistant",
            "content": "Roaming is now enabled, but MMS still requires prerequisites.",
        }
    )

    assert scaffold.account_roaming_enabled is True
    assert scaffold.terminal_mms_projection_due() is True


def test_telecom_user_projector_compresses_post_text_wifi_repair() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v3")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.mms_verified = False
    scaffold.mms_failed_after_prereqs = True
    scaffold.mark_projected_user_tool_actions(
        [
            ("check_wifi_calling_status", {}),
            ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
            (
                "grant_app_permission",
                {"app_name": "messaging", "permission": "storage"},
            ),
        ]
    )

    actions = _project_user_actions_after_observed_text(
        scaffold,
        (
            "Wi-Fi Calling is on, SMS and storage permissions are granted, "
            "and MMS still has not succeeded."
        ),
    )

    assert actions == [("toggle_wifi_calling", {})]
    assert scaffold.wifi_calling_safe is True


def test_telecom_terminal_projection_waits_for_extended_mms_recovery() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v4")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.mms_verified = False
    scaffold.mms_failed_after_prereqs = True
    scaffold.messaging_sms_permission = True
    scaffold.messaging_storage_permission = True
    scaffold.wifi_calling_safe = None

    assert scaffold.terminal_mms_projection_due() is False

    scaffold.wifi_calling_safe = True

    assert scaffold.terminal_mms_projection_due() is True


def test_telecom_harness_compression_v5_observes_multi_tool_user_results() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v5")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.mms_verified = False
    scaffold.mms_failed_after_prereqs = True
    scaffold.mark_projected_user_tool_actions(
        [
            ("check_wifi_calling_status", {}),
            ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
            (
                "grant_app_permission",
                {"app_name": "messaging", "permission": "storage"},
            ),
        ]
    )

    scaffold.observe_incoming_message(
        SimpleNamespace(
            role="tool",
            tool_messages=[
                SimpleNamespace(content="Wi-Fi Calling is currently turned ON."),
                SimpleNamespace(content="Success. Permission 'sms' granted to app 'messaging'."),
                SimpleNamespace(
                    content="Success. Permission 'storage' granted to app 'messaging'."
                ),
            ],
        )
    )

    assert scaffold.wifi_calling_safe is False
    assert scaffold.messaging_sms_permission is True
    assert scaffold.messaging_storage_permission is True
    assert scaffold.projected_user_tool_actions() == [("toggle_wifi_calling", {})]

    scaffold.mark_projected_user_tool_actions([("toggle_wifi_calling", {})])
    scaffold.observe_tool_output("toggle_wifi_calling", "Wi-Fi Calling is now OFF.")

    assert scaffold.terminal_mms_projection_due() is True


def test_telecom_harness_compression_v6_allows_phone_side_recheck_after_extended_repair() -> None:
    v5 = build_workflow_order_scaffold("telecom-mms-harness-compression-v5")
    v6 = build_workflow_order_scaffold("telecom-mms-harness-compression-v6")

    for scaffold in (v5, v6):
        assert isinstance(scaffold, TelecomMmsWorkflowOrder)
        scaffold.airplane_off = True
        scaffold.sim_active = True
        scaffold.mobile_data_on = True
        scaffold.non_2g_network = True
        scaffold.apn_valid = True
        scaffold.device_roaming_on = True
        scaffold.account_roaming_enabled = None
        scaffold.mms_verified = False
        scaffold.mms_failed_after_prereqs = True
        scaffold.wifi_calling_safe = True
        scaffold.messaging_sms_permission = True
        scaffold.messaging_storage_permission = True

    assert isinstance(v5, TelecomMmsWorkflowOrder)
    assert isinstance(v6, TelecomMmsWorkflowOrder)
    assert v5.terminal_mms_projection_due() is False
    assert v6.terminal_mms_projection_due() is True

    v6.account_roaming_enabled = False

    assert v6.terminal_mms_projection_due() is False


def test_telecom_harness_compression_v7_runs_extended_recovery_before_first_terminal() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v7")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True
    scaffold.observe_assistant_text(
        "The data refuel was successful for line L1002. Please run can_send_mms now."
    )

    assert scaffold.data_refueled is True
    assert scaffold.projected_user_tool_actions() == [
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "storage"},
        ),
    ]


def test_telecom_harness_compression_v8_projects_terminal_after_proactive_repair() -> None:
    v7 = build_workflow_order_scaffold("telecom-mms-harness-compression-v7")
    v8 = build_workflow_order_scaffold("telecom-mms-harness-compression-v8")

    for scaffold in (v7, v8):
        assert isinstance(scaffold, TelecomMmsWorkflowOrder)
        scaffold.airplane_off = True
        scaffold.sim_active = True
        scaffold.mobile_data_on = True
        scaffold.non_2g_network = True
        scaffold.apn_valid = True
        scaffold.device_roaming_on = True
        scaffold.data_refueled = True
        scaffold.wifi_calling_safe = True
        scaffold.messaging_sms_permission = True
        scaffold.messaging_storage_permission = True

    assert isinstance(v7, TelecomMmsWorkflowOrder)
    assert isinstance(v8, TelecomMmsWorkflowOrder)
    assert v7.terminal_mms_projection_due() is False
    assert v8.terminal_mms_projection_due() is True


def test_telecom_harness_compression_v9_checks_apn_before_reset() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v9")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = None
    scaffold.device_roaming_on = False

    actions = scaffold.projected_user_tool_actions()

    assert ("check_apn_settings", {}) in actions
    assert ("reset_apn_settings", {}) not in actions
    assert ("reboot_device", {}) not in actions
    assert ("toggle_roaming", {}) in actions


def test_telecom_harness_compression_v9_blocks_post_refuel_account_relookup() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v9")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = True
    scaffold.observe_tool_output(
        "refuel_data",
        '{"message":"Successfully added 2.0 GB of data for line L1002 for $4.00",'
        '"new_data_refueling_gb":"2.0","charge":"4.0"}',
    )

    assert scaffold.post_refuel_account_relookup_blocked() is True
    assert scaffold.redundant_account_lookup_tool("get_customer_by_id") is True
    assert scaffold.redundant_account_lookup_tool("get_customer_by_phone") is True
    assert scaffold.redundant_account_lookup_tool("get_data_usage") is False
    assert "Do not call get_customer_by_id" in scaffold.prompt_hint()

    correction = scaffold.branch_correction_prompt("get_customer_by_id")

    assert correction is not None
    assert "repeat account/customer lookup" in correction
    assert "bounded extended MMS recovery bundle" in correction


def test_telecom_harness_compression_v10_defers_roaming_until_after_apn_observation() -> None:
    v9 = build_workflow_order_scaffold("telecom-mms-harness-compression-v9")
    v10 = build_workflow_order_scaffold("telecom-mms-harness-compression-v10")

    for scaffold in (v9, v10):
        assert isinstance(scaffold, TelecomMmsWorkflowOrder)
        scaffold.airplane_off = True
        scaffold.sim_active = True
        scaffold.mobile_data_on = True
        scaffold.non_2g_network = True
        scaffold.apn_valid = None
        scaffold.device_roaming_on = False

    assert isinstance(v9, TelecomMmsWorkflowOrder)
    assert isinstance(v10, TelecomMmsWorkflowOrder)

    assert v9.projected_user_tool_actions() == [
        ("check_apn_settings", {}),
        ("toggle_roaming", {}),
    ]
    assert v10.projected_user_tool_actions() == [("check_apn_settings", {})]

    v10.mark_projected_user_tool_actions([("check_apn_settings", {})])
    v10.observe_tool_output(
        "check_apn_settings",
        "Current APN Name: internet\nMMSC URL (for picture messages): Not Set",
    )

    assert v10.projected_user_tool_actions() == [
        ("reset_apn_settings", {}),
        ("reboot_device", {}),
        ("check_apn_settings", {}),
        ("toggle_roaming", {}),
    ]


def test_telecom_harness_compression_v9_runs_proactive_extended_recovery_without_first_terminal_failure() -> (
    None
):
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v9")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.mms_verified = None

    actions = scaffold.projected_user_tool_actions()

    assert actions == [
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "storage"},
        ),
    ]

    scaffold.mark_projected_user_tool_actions(actions)
    scaffold.observe_incoming_message(
        SimpleNamespace(
            role="tool",
            tool_messages=[
                SimpleNamespace(content="Wi-Fi Calling is currently turned ON."),
                SimpleNamespace(content="Success. Permission 'sms' granted to app 'messaging'."),
                SimpleNamespace(
                    content="Success. Permission 'storage' granted to app 'messaging'."
                ),
            ],
        )
    )

    assert scaffold.projected_user_tool_actions() == [
        ("toggle_wifi_calling", {}),
        ("can_send_mms", {}),
    ]

    scaffold.mark_projected_user_tool_actions([("toggle_wifi_calling", {})])
    scaffold.observe_tool_output("toggle_wifi_calling", "Wi-Fi Calling is now OFF.")

    assert scaffold.terminal_mms_projection_due() is True


def test_telecom_harness_compression_v9_reads_below_limit_assistant_text() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v9")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.observe_assistant_text("Your data usage is below the limit, so data is fine.")

    assert scaffold.data_usage_exceeded is False
    assert scaffold.projected_user_tool_actions() == [
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "storage"},
        ),
    ]


def test_telecom_harness_compression_v9_rechecks_apn_after_reset() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v9")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "check_network_status",
        (
            "Airplane Mode: OFF\n"
            "SIM Card Status: active\n"
            "Mobile Data Enabled: Yes\n"
            "Cellular Network Type: 5G\n"
            "Data Roaming Enabled: Yes"
        ),
    )
    first_actions = scaffold.projected_user_tool_actions()
    assert first_actions == [("check_apn_settings", {})]
    scaffold.mark_projected_user_tool_actions(first_actions)
    scaffold.observe_tool_output(
        "check_apn_settings",
        "Current APN Name: internet\nMMSC URL (for picture messages): Not Set",
    )

    assert scaffold.projected_user_tool_actions() == [
        ("reset_apn_settings", {}),
        ("reboot_device", {}),
        ("check_apn_settings", {}),
    ]


def test_tau2_user_projector_replaces_premature_terminal_with_repair_actions() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v9")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = False
    scaffold.device_roaming_on = True
    tool_calls = [SimpleNamespace(name="can_send_mms")]

    assert _project_user_actions_for_premature_terminal(scaffold, tool_calls) == [
        ("reset_apn_settings", {}),
        ("reboot_device", {}),
        ("check_apn_settings", {}),
    ]


def test_telecom_user_projector_reads_assistant_account_repair_being_enabled() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mark_projected_user_tool_actions(
        [
            ("toggle_airplane_mode", {}),
            ("reseat_sim_card", {}),
            ("toggle_data", {}),
            ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
            ("check_apn_settings", {}),
            ("toggle_roaming", {}),
        ]
    )
    scaffold.observe_incoming_message(
        {
            "role": "assistant",
            "content": (
                "Roaming being enabled is noted, but MMS still needs the "
                "required prerequisites confirmed first."
            ),
        }
    )

    assert scaffold.account_roaming_enabled is True
    assert scaffold.terminal_mms_projection_due() is True


def test_telecom_workflow_order_reads_grounded_user_status_summary() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-late-compression-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_incoming_message(
        {
            "role": "user",
            "content": (
                "The affected phone number is 555-123-2002. "
                "Airplane Mode is off, the SIM was reseated, mobile data is on, "
                "the preferred network is now 4G/5G, APN settings show the MMSC URL "
                "is set, and data roaming is now on."
            ),
        }
    )

    assert scaffold.blockers_clear() is True
    assert scaffold.device_roaming_on is True
    assert scaffold.active_phone_number == "555-123-2002"
    assert scaffold.account_identity_lookup_due() is True


def test_telecom_phased_recovery_scaffold_advances_small_native_user_phases() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-phased-recovery-v1")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.phased_recovery is True
    assert "Phase 1 signal/SIM" in scaffold.prompt_hint()

    scaffold.observe_tool_output("toggle_airplane_mode", "Airplane Mode is now OFF.")
    scaffold.observe_tool_output("reseat_sim_card", "SIM card re-seated successfully.")
    assert "Phase 2 data/network" in scaffold.prompt_hint()

    scaffold.observe_tool_output("toggle_data", "Mobile data is now on.")
    scaffold.observe_tool_output("set_network_mode_preference", "Network Type: 4G")
    assert "Phase 3 APN/MMSC" in scaffold.prompt_hint()

    scaffold.observe_tool_output("reset_apn_settings", "MMSC URL: http://mms.example")
    assert "Phase 4 terminal verifier" in scaffold.prompt_hint()

    scaffold.observe_tool_output("can_send_mms", "Your messaging app cannot send MMS messages.")
    assert "Phase 5 roaming recovery" in scaffold.prompt_hint()


def test_telecom_harness_compression_v11_projects_assistant_requested_user_actions() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v11")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    actions = scaffold.assistant_requested_user_tool_actions(
        "For MMS, please do this next and report the results together: "
        "1. Check Wi-Fi Calling status. "
        "2. If Wi-Fi Calling is ON, turn it OFF. "
        "3. Grant the Messaging app SMS permission. "
        "4. Grant the Messaging app Storage permission."
    )

    assert actions == [
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
    ]


def test_telecom_harness_compression_v10_does_not_project_assistant_requested_actions() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v10")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert (
        scaffold.assistant_requested_user_tool_actions("Grant the Messaging app SMS permission.")
        == []
    )


def test_telecom_harness_compression_v12_projects_terminal_after_requested_toggle() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v12")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.messaging_sms_permission = True
    scaffold.messaging_storage_permission = True
    scaffold.wifi_calling_safe = False

    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run `toggle_wifi_calling` to turn Wi-Fi Calling OFF. "
        "After that, run the final `can_send_mms` check."
    )

    assert actions == [("toggle_wifi_calling", {}), ("can_send_mms", {})]


def test_telecom_harness_compression_reads_refuel_applied_assistant_text() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v13")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_assistant_text("The 2.0 GB data refuel was applied successfully.")

    assert scaffold.data_refueled is True
    assert scaffold.data_usage_exceeded is False


def test_telecom_harness_compression_v13_pairs_apn_observation_with_roaming_toggle() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v13")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "check_network_status",
        (
            "Airplane Mode: OFF\n"
            "SIM Card Status: active\n"
            "Mobile Data Enabled: Yes\n"
            "Cellular Network Type: 5G\n"
            "Data Roaming Enabled: No"
        ),
    )

    assert scaffold.projected_user_tool_actions() == [
        ("check_apn_settings", {}),
        ("toggle_roaming", {}),
    ]


def test_telecom_harness_compression_v14_defers_phone_roaming_to_extended_bundle() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v14")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "check_network_status",
        (
            "Airplane Mode: OFF\n"
            "SIM Card Status: active\n"
            "Mobile Data Enabled: Yes\n"
            "Cellular Network Type: 5G\n"
            "Data Roaming Enabled: No"
        ),
    )

    assert scaffold.projected_user_tool_actions() == [("check_apn_settings", {})]

    scaffold.mark_projected_user_tool_actions([("check_apn_settings", {})])
    scaffold.observe_tool_output(
        "check_apn_settings",
        "Current APN Name: internet\nMMSC URL (for picture messages): http://mms.test",
    )
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = True
    scaffold.data_refueled = True
    scaffold.data_usage_exceeded = False

    assert scaffold.projected_user_tool_actions() == [
        ("toggle_roaming", {}),
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
    ]


def test_telecom_harness_compression_v14_projects_terminal_after_roaming_and_wifi_repairs() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v14")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.data_refueled = True
    scaffold.data_usage_exceeded = False
    scaffold.wifi_calling_safe = False
    scaffold.messaging_sms_permission = True
    scaffold.messaging_storage_permission = True

    assert scaffold.projected_user_tool_actions() == [
        ("toggle_roaming", {}),
        ("toggle_wifi_calling", {}),
        ("can_send_mms", {}),
    ]


def test_telecom_harness_compression_v14_corrects_terminal_before_deferred_roaming() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v14")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.data_refueled = True
    scaffold.data_usage_exceeded = False

    correction = scaffold.branch_correction_prompt("Please run can_send_mms now.")

    assert correction is not None
    assert "toggle_roaming" in correction
    assert "Do not ask for can_send_mms yet" in correction


def test_telecom_harness_compression_v14_adds_deferred_roaming_to_assistant_requested_bundle() -> (
    None
):
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v14")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.data_refueled = True
    scaffold.data_usage_exceeded = False

    actions = scaffold.assistant_requested_user_tool_actions(
        "Next, please run these phone actions: check_wifi_calling_status; "
        'grant_app_permission(app_name="messaging", permission="sms"); '
        'grant_app_permission(app_name="messaging", permission="storage").'
    )

    assert actions == [
        ("toggle_roaming", {}),
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
    ]


def test_telecom_harness_compression_v14_projects_conditional_wifi_toggle_in_requested_bundle() -> (
    None
):
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v14")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.data_refueled = True
    scaffold.data_usage_exceeded = False

    actions = scaffold.assistant_requested_user_tool_actions(
        "Before testing MMS, please run this MMS recovery bundle: "
        "1. `check_wifi_calling_status` "
        "2. If Wi-Fi Calling is ON: `toggle_wifi_calling` "
        '3. `grant_app_permission(app_name="messaging", permission="sms")` '
        '4. `grant_app_permission(app_name="messaging", permission="storage")`'
    )

    assert actions == [
        ("toggle_roaming", {}),
        ("check_wifi_calling_status", {}),
        ("toggle_wifi_calling", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
    ]


def test_telecom_harness_compression_v15_projects_terminal_inside_extended_bundle() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v15")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.data_refueled = True
    scaffold.data_usage_exceeded = False

    actions = scaffold.assistant_requested_user_tool_actions(
        "To finish MMS recovery, please run these phone actions and send me the results: "
        "1. `check_wifi_calling_status` "
        "2. If Wi-Fi Calling is ON: `toggle_wifi_calling` "
        '3. `grant_app_permission(app_name="messaging", permission="sms")` '
        '4. `grant_app_permission(app_name="messaging", permission="storage")`'
    )

    assert actions == [
        ("toggle_roaming", {}),
        ("check_wifi_calling_status", {}),
        ("toggle_wifi_calling", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
        ("can_send_mms", {}),
    ]


def test_telecom_harness_compression_v15_respects_terminal_deferral_text() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v15")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.data_refueled = True
    scaffold.data_usage_exceeded = False

    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run `check_wifi_calling_status`, grant the messaging SMS permission, "
        "and grant the messaging storage permission. Do not run `can_send_mms` yet."
    )

    assert actions == [
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
    ]


def test_telecom_harness_compression_v15_trusts_explicit_terminal_request_after_agent_guard() -> (
    None
):
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v15")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = False
    scaffold.device_roaming_on = False
    scaffold.data_refueled = True
    scaffold.data_usage_exceeded = False

    actions = scaffold.assistant_requested_user_tool_actions(
        "Thanks - 2.0 GB has been added to line L1002. "
        "To finish MMS recovery, please run these actions in order: "
        "`check_wifi_calling_status`; if Wi-Fi Calling is ON, `toggle_wifi_calling`; "
        '`grant_app_permission(app_name="messaging", permission="sms")`; '
        '`grant_app_permission(app_name="messaging", permission="storage")`; '
        "`can_send_mms`."
    )

    assert actions == [
        ("toggle_roaming", {}),
        ("check_wifi_calling_status", {}),
        ("toggle_wifi_calling", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
        ("can_send_mms", {}),
    ]


def test_telecom_harness_compression_v16_does_not_preemptively_toggle_unknown_wifi() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v16")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False

    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run these phone actions in order and tell me the results: "
        "1. `check_wifi_calling_status` "
        "2. If Wi-Fi Calling is ON: `toggle_wifi_calling` "
        '3. `grant_app_permission(app_name="messaging", permission="sms")` '
        '4. `grant_app_permission(app_name="messaging", permission="storage")` '
        "5. `can_send_mms`"
    )

    assert actions == [
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
    ]


def test_telecom_harness_compression_v16_projects_terminal_after_wifi_off_observation() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v16")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.mark_projected_user_tool_actions(
        [
            ("check_wifi_calling_status", {}),
            ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
            ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
        ]
    )
    scaffold.observe_tool_output(
        "check_wifi_calling_status", "Wi-Fi Calling is currently turned OFF."
    )
    scaffold.observe_tool_output(
        "grant_app_permission",
        "Success. Permission 'sms' granted to app 'messaging'.",
    )
    scaffold.observe_tool_output(
        "grant_app_permission",
        "Success. Permission 'storage' granted to app 'messaging'.",
    )

    assert scaffold.projected_user_tool_actions() == [("can_send_mms", {})]


def test_telecom_harness_compression_v16_treats_within_plan_text_as_data_clear() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v16")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.observe_assistant_text(
        "Your line's data usage is within the plan limit, so data allowance is not the blocker."
    )

    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run these phone actions in order and send me the results: "
        "1. `check_wifi_calling_status` "
        "2. If Wi-Fi Calling is ON, run `toggle_wifi_calling` "
        '3. `grant_app_permission(app_name="messaging", permission="sms")` '
        '4. `grant_app_permission(app_name="messaging", permission="storage")` '
        "5. `can_send_mms`"
    )

    assert actions == [
        ("toggle_roaming", {}),
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
    ]


def test_telecom_harness_compression_v17_keeps_wifi_repair_and_terminal_together() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v17")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.wifi_calling_safe = False
    scaffold.messaging_sms_permission = True
    scaffold.messaging_storage_permission = True

    actions = scaffold.assistant_requested_user_tool_actions(
        "Yes. Since Wi-Fi Calling is ON, please run: "
        "1. `toggle_wifi_calling` "
        "2. `can_send_mms` "
        "Tell me whether `can_send_mms` succeeds."
    )

    assert actions == [
        ("toggle_roaming", {}),
        ("toggle_wifi_calling", {}),
        ("can_send_mms", {}),
    ]


def test_telecom_harness_compression_v17_does_not_duplicate_phone_roaming_when_on() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v17")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.wifi_calling_safe = False
    scaffold.messaging_sms_permission = True
    scaffold.messaging_storage_permission = True

    actions = scaffold.assistant_requested_user_tool_actions(
        "Since Wi-Fi Calling is ON, run `toggle_wifi_calling`, then `can_send_mms`."
    )

    assert actions == [
        ("toggle_wifi_calling", {}),
        ("can_send_mms", {}),
    ]


def test_telecom_harness_compression_v18_repairs_roaming_when_terminal_is_deferred() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v18")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"

    actions = scaffold.assistant_requested_user_tool_actions(
        "Core MMS prerequisites look good. Please run this recovery bundle: "
        "1. `check_wifi_calling_status` "
        "2. If Wi-Fi Calling is ON: `toggle_wifi_calling` "
        '3. `grant_app_permission(app_name="messaging", permission="sms")` '
        '4. `grant_app_permission(app_name="messaging", permission="storage")` '
        "5. `can_send_mms`"
    )

    assert actions == [
        ("toggle_roaming", {}),
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
    ]


def test_telecom_harness_compression_v19_runs_terminal_with_unknown_wifi_without_toggle() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v19")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.data_refueled = True

    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run these phone actions in order and tell me the results: "
        "1. `check_wifi_calling_status` "
        "2. If Wi-Fi Calling is ON, run `toggle_wifi_calling` "
        '3. `grant_app_permission(app_name="messaging", permission="sms")` '
        '4. `grant_app_permission(app_name="messaging", permission="storage")` '
        "5. `can_send_mms`"
    )

    assert actions == [
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
        ("can_send_mms", {}),
    ]


def test_telecom_harness_compression_v20_trusts_apn_reset_reboot_without_recheck() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v20")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = False

    actions = scaffold.projected_user_tool_actions()

    assert actions == [("reset_apn_settings", {}), ("reboot_device", {})]

    scaffold.observe_outgoing_tool_calls(
        [
            SimpleNamespace(name="reset_apn_settings"),
            SimpleNamespace(name="reboot_device"),
        ]
    )
    scaffold.observe_tool_output(
        "reset_apn_settings",
        "APN settings will reset at reboot.\nStatus Bar: Excellent 5G",
    )
    scaffold.observe_tool_output(
        "reboot_device",
        "Resetting APN settings...\nRestarting network services...",
    )

    assert scaffold.apn_valid is True


def test_telecom_harness_compression_v21_infers_data_exhaustion_from_line_details() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v21")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"

    scaffold.observe_tool_output(
        "get_details_by_id",
        (
            '{"line_id":"L1002","phone_number":"555-123-2002","plan_id":"P1002",'
            '"data_used_gb":15.1,"data_refueling_gb":0.0,"roaming_enabled":true}'
        ),
    )

    assert scaffold.data_usage_exceeded is True
    assert scaffold.data_usage_lookup_due() is False
    assert scaffold.data_refuel_due() is True


def test_telecom_harness_compression_v21_defers_terminal_with_unknown_wifi() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v21")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_line_id = "L1002"
    scaffold.data_refueled = True

    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run these phone actions in order and tell me the results: "
        "1. `check_wifi_calling_status` "
        "2. If Wi-Fi Calling is ON, run `toggle_wifi_calling` "
        '3. `grant_app_permission(app_name="messaging", permission="sms")` '
        '4. `grant_app_permission(app_name="messaging", permission="storage")` '
        "5. `can_send_mms`"
    )

    assert actions == [
        ("check_wifi_calling_status", {}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "sms"}),
        ("grant_app_permission", {"app_name": "messaging", "permission": "storage"}),
    ]


def test_telecom_harness_compression_v22_skips_apn_observation_after_bad_network() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v22")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = False
    scaffold.apn_valid = None

    actions = scaffold.projected_user_tool_actions()

    assert actions == [
        ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
        ("reset_apn_settings", {}),
        ("reboot_device", {}),
    ]


def test_telecom_harness_compression_v23_skips_apn_observation_after_no_service() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v23")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "check_network_status",
        (
            "Airplane Mode: ON\n"
            "SIM Card Status: missing\n"
            "Cellular Connection: no_service\n"
            "Cellular Network Type: none\n"
            "Mobile Data Enabled: No\n"
            "Data Roaming Enabled: No"
        ),
    )

    actions = scaffold.projected_user_tool_actions()

    assert actions == [
        ("toggle_airplane_mode", {}),
        ("reseat_sim_card", {}),
        ("toggle_data", {}),
        ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
        ("reset_apn_settings", {}),
        ("reboot_device", {}),
    ]


def test_telecom_harness_compression_v24_keeps_projected_wifi_toggle_terminal() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v24")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.data_refueled = True
    scaffold.mms_verified = False
    scaffold.mms_failed_after_prereqs = True
    scaffold.wifi_calling_safe = False
    scaffold.messaging_sms_permission = True
    scaffold.messaging_storage_permission = True

    actions = scaffold.projected_user_tool_actions()

    assert actions == [
        ("toggle_wifi_calling", {}),
        ("can_send_mms", {}),
    ]


def test_tau2_user_projector_continues_after_projected_only_turns() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v25")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert _workflow_user_projection_ready(scaffold, messages_seen=0) is False

    scaffold.mark_projected_user_tool_actions([("check_network_status", {})])

    assert _workflow_user_projection_ready(scaffold, messages_seen=0) is True
    assert _workflow_user_projection_ready(scaffold, messages_seen=1) is True


def test_telecom_harness_compression_v26_completes_recovery_on_terminal_request() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v26")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.data_refueled = True
    scaffold.wifi_calling_safe = None
    scaffold.messaging_sms_permission = None
    scaffold.messaging_storage_permission = None

    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run `can_send_mms` now and tell me the result."
    )

    assert actions == [
        ("toggle_roaming", {}),
        ("check_wifi_calling_status", {}),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "sms"},
        ),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "storage"},
        ),
    ]

    scaffold.mark_projected_user_tool_actions(actions)
    scaffold.observe_tool_output("toggle_roaming", "Data Roaming is now ON.")
    scaffold.observe_tool_output(
        "check_wifi_calling_status",
        "Wi-Fi Calling is currently turned ON.",
    )
    scaffold.observe_tool_output(
        "grant_app_permission",
        "Success. Permission 'sms' granted to app 'messaging'.",
    )
    scaffold.observe_tool_output(
        "grant_app_permission",
        "Success. Permission 'storage' granted to app 'messaging'.",
    )

    assert scaffold.projected_user_tool_actions() == [
        ("toggle_wifi_calling", {}),
        ("can_send_mms", {}),
    ]


def test_telecom_harness_compression_v27_dedupes_terminal_requested_recovery() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v27")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.data_refueled = True
    scaffold.wifi_calling_safe = None
    scaffold.messaging_sms_permission = None
    scaffold.messaging_storage_permission = None

    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run check_wifi_calling_status, grant_app_permission for "
        "messaging sms and storage, then run can_send_mms."
    )

    assert actions == [
        ("toggle_roaming", {}),
        ("check_wifi_calling_status", {}),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "sms"},
        ),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "storage"},
        ),
    ]


def test_telecom_harness_compression_v28_does_not_verify_before_wifi_toggle() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v28")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.data_refueled = True
    scaffold.wifi_calling_safe = False
    scaffold.messaging_sms_permission = True
    scaffold.messaging_storage_permission = True
    scaffold.mark_projected_user_tool_actions(
        [
            ("toggle_roaming", {}),
            ("check_wifi_calling_status", {}),
            (
                "grant_app_permission",
                {"app_name": "messaging", "permission": "sms"},
            ),
            (
                "grant_app_permission",
                {"app_name": "messaging", "permission": "storage"},
            ),
        ]
    )

    assert scaffold.projected_user_tool_actions() == [
        ("toggle_wifi_calling", {}),
        ("can_send_mms", {}),
    ]


def test_telecom_harness_compression_v29_stops_after_mobile_data_excellent() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v29")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_stop_after_mobile_data_excellent is True
    assert scaffold.terminal_mobile_data_stop_due(
        "Speed Test Result: 275.00 Mbps (Excellent). Connection is very fast."
    )


def test_tau2_user_projector_loads_v29_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v29")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_stop_after_mobile_data_excellent is True


def test_telecom_harness_compression_v30_projects_speed_test_after_mobile_repair() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v30")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_speed_test_after_mobile_data_repair is True
    assert scaffold.projected_mobile_data_speed_test_after_repair(
        "Data Roaming is now ON. Status Bar: Excellent | 5G | Data Enabled"
    ) == [("run_speed_test", {})]


def test_tau2_user_projector_loads_v30_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v30")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_speed_test_after_mobile_data_repair is True


def test_telecom_harness_compression_v31_projects_mobile_data_requested_reads() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v31")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run check_data_restriction_status. If Data Saver is ON, run "
        "toggle_data_saver_mode. Then run check_vpn_status. If VPN is connected, "
        "run disconnect_vpn. Finally run run_speed_test."
    )

    assert actions == [
        ("check_data_restriction_status", {}),
        ("check_vpn_status", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v31_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v31")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_assistant_requested_actions is True


def test_telecom_harness_compression_v32_projects_natural_language_speed_test() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v32")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run a speed test now to confirm whether mobile data is working."
    )

    assert actions == [("run_speed_test", {})]


def test_telecom_harness_compression_v32_repeats_speed_test_after_repair() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v32")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mark_projected_user_tool_actions([("run_speed_test", {})])

    assert scaffold.projected_mobile_data_speed_test_after_repair(
        "Data Saver is now OFF. Status Bar: Excellent | 5G | Data Enabled"
    ) == [("run_speed_test", {})]


def test_tau2_user_projector_loads_v32_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v32")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_assistant_requested_actions is True


def test_telecom_harness_compression_v33_repairs_known_mobile_data_state() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v33")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "check_network_status",
        "Status Bar: Excellent | 5G | Data Enabled | Data Saver | VPN Connected",
    )

    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run check_data_restriction_status. If Data Saver is ON, run "
        "toggle_data_saver_mode. Then run check_vpn_status. If VPN is connected, "
        "run disconnect_vpn. Finally run run_speed_test."
    )

    assert actions == [
        ("toggle_data_saver_mode", {}),
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_telecom_harness_compression_v33_recovers_after_speed_failure() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v33")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.device_roaming_on = False
    scaffold.vpn_connected = True

    assert scaffold.projected_mobile_data_recovery_after_speed_failure(
        "Speed test failed: No Connection."
    ) == [
        ("toggle_roaming", {}),
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v33_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v33")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_known_state_repairs is True
    assert scaffold.project_mobile_data_speed_failure_recovery is True


def test_telecom_harness_compression_v34_redirects_mms_terminal_for_mobile_data() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v34")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_user_text("My mobile data is slow and I need excellent internet speed.")
    scaffold.device_roaming_on = False
    scaffold.vpn_connected = True

    assert scaffold.assistant_requested_user_tool_actions("Please run `can_send_mms()`.") == [
        ("toggle_roaming", {}),
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v34_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v34")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_terminal_instead_of_mms is True


def test_telecom_harness_compression_v35_stops_after_bundled_excellent_speed() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v35")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "run_speed_test",
        "Speed Test Result: 275.00 Mbps (Excellent). Connection is very fast.",
    )

    assert scaffold.terminal_mobile_data_stop_due("")


def test_tau2_user_projector_loads_v35_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v35")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_terminal_instead_of_mms is True


def test_telecom_harness_compression_v36_projects_natural_mobile_repair() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v36")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_user_text("My mobile data is slow and I need excellent internet speed.")
    scaffold.device_roaming_on = False
    scaffold.vpn_connected = True

    assert scaffold.assistant_requested_user_tool_actions(
        "Since you are abroad, please turn on Data Roaming on your phone if it "
        "is not already on, then check whether mobile data speed improves."
    ) == [
        ("toggle_roaming", {}),
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v36_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v36")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_terminal_instead_of_mms is True


def test_telecom_harness_compression_v37_does_not_stop_on_status_bar_excellent() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v37")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "run_speed_test",
        "Status Bar: Excellent | 5G | Data Enabled | VPN Connected",
    )

    assert not scaffold.terminal_mobile_data_stop_due("")


def test_tau2_user_projector_loads_v37_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v37")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_terminal_instead_of_mms is True


def test_telecom_harness_compression_v38_adds_vpn_repair_to_roaming_request() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v38")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_user_text("My mobile data is slow and I need excellent internet speed.")
    scaffold.device_roaming_on = False
    scaffold.vpn_connected = True

    assert scaffold.assistant_requested_user_tool_actions(
        "Please run `toggle_roaming` and then `run_speed_test`."
    ) == [
        ("toggle_roaming", {}),
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v38_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v38")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_terminal_instead_of_mms is True


def test_telecom_harness_compression_v39_projects_mobile_terminal_after_refuel() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v39")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_user_text("My mobile data is slow and I need excellent internet speed.")
    scaffold.data_refueled = True
    scaffold.device_roaming_on = False
    scaffold.vpn_connected = True

    assert scaffold.projected_user_tool_actions() == [
        ("toggle_roaming", {}),
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_telecom_harness_compression_v39_suppresses_mms_branch_after_refuel() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v39")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_user_text("My mobile data is slow and I need excellent internet speed.")
    scaffold.data_refueled = True
    scaffold.device_roaming_on = True
    scaffold.vpn_connected = True
    scaffold.wifi_calling_safe = None
    scaffold.messaging_sms_permission = False
    scaffold.messaging_storage_permission = False

    actions = scaffold.projected_user_tool_actions()

    assert actions == [
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]
    assert ("can_send_mms", {}) not in actions
    assert not any(name == "grant_app_permission" for name, _arguments in actions)


def test_tau2_user_projector_loads_v39_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v39")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_terminal_after_refuel is True


def test_telecom_harness_compression_v40_uses_instruction_intent_after_refuel() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v40")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_user_text(
        "I am abroad in France with no Wi-Fi. My mobile data keeps stopping "
        "or gets really slow, and I need excellent internet speed."
    )
    scaffold.data_refueled = True
    scaffold.device_roaming_on = False
    scaffold.vpn_connected = True

    assert scaffold.assistant_requested_user_tool_actions(
        "Please reboot your phone, then make sure Data Roaming is ON since "
        "you are abroad. After that, try your mobile data again."
    ) == [
        ("toggle_roaming", {}),
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v40_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v40")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_terminal_after_refuel is True


def test_telecom_harness_compression_v41_repeats_speed_test_after_refuel_repairs() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v41")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_user_text(
        "My mobile data is slow, I am abroad in France, and I need excellent speed."
    )
    scaffold.mark_projected_user_tool_actions([("run_speed_test", {})])
    scaffold.data_refueled = True
    scaffold.device_roaming_on = True
    scaffold.data_saver_on = True
    scaffold.vpn_connected = True

    assert scaffold.projected_user_tool_actions() == [
        ("toggle_data_saver_mode", {}),
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v41_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v41")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.repeat_mobile_data_speed_test_after_terminal_repairs is True


def test_telecom_harness_compression_v42_repairs_known_data_saver_from_status_check() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v42")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_user_text(
        "My mobile data is slow, I am abroad in France, and I need excellent speed."
    )
    scaffold.data_saver_on = True
    scaffold.vpn_connected = False

    assert scaffold.assistant_requested_user_tool_actions(
        "Please run these phone checks and send me the results:\n"
        "1. `run_speed_test`\n"
        "2. `check_data_restriction_status`\n"
        "3. `check_vpn_status`"
    ) == [
        ("toggle_data_saver_mode", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v42_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v42")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_known_mobile_data_repairs_from_status_checks is True


def test_telecom_harness_compression_v43_collapses_unknown_wifi_terminal_bundle() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v43")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.data_refueled = True
    scaffold.wifi_calling_safe = None
    scaffold.messaging_sms_permission = None
    scaffold.messaging_storage_permission = None

    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run these phone actions in order: "
        "check_wifi_calling_status; if Wi-Fi Calling is ON, toggle_wifi_calling; "
        "grant_app_permission for messaging sms; "
        "grant_app_permission for messaging storage; then can_send_mms."
    )

    assert actions == [
        ("toggle_roaming", {}),
        ("check_wifi_calling_status", {}),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "sms"},
        ),
        (
            "grant_app_permission",
            {"app_name": "messaging", "permission": "storage"},
        ),
        ("toggle_wifi_calling", {}),
        ("can_send_mms", {}),
    ]


def test_tau2_user_projector_loads_v43_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v43")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_conditional_wifi_toggle_when_unknown is True


def test_telecom_harness_compression_v44_requires_current_speed_test_for_stop() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v44")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_speed_excellent = True

    assert (
        scaffold.terminal_mobile_data_stop_due("Great, your mobile data should be fixed.") is False
    )
    assert (
        scaffold.terminal_mobile_data_stop_due(
            "Speed Test Result: 275.00 Mbps (Excellent). Your mobile data is connected."
        )
        is True
    )


def test_tau2_user_projector_loads_v44_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v44")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_conditional_wifi_toggle_when_unknown is True
    assert scaffold.project_known_mobile_data_repairs_from_status_checks is True
    assert scaffold.require_current_speed_test_for_mobile_data_stop is True


def test_telecom_harness_compression_v45_does_not_treat_good_news_as_speed_failure() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v45")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.data_saver_on = False
    scaffold.vpn_connected = False

    assert (
        scaffold.projected_mobile_data_recovery_after_speed_failure(
            "Good news: Data Saver and VPN are not causing it. "
            "Next, please run check_network_mode_preference and run_speed_test."
        )
        == []
    )
    assert (
        scaffold.projected_mobile_data_recovery_after_speed_failure(
            "Speed Test Result: 55.00 Mbps (Good). Connection is good for most activities."
        )
        == []
    )


def test_telecom_harness_compression_v45_records_data_saver_and_vpn_off() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v45")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output("check_data_restriction_status", "Data Saver mode is OFF.")
    scaffold.observe_tool_output("check_vpn_status", "VPN is turned OFF.")

    assert scaffold.data_saver_on is False
    assert scaffold.vpn_connected is False


def test_tau2_user_projector_loads_v45_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v45")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.require_current_speed_test_for_mobile_data_stop is True
    assert scaffold.project_known_mobile_data_repairs_from_status_checks is True


def test_telecom_harness_compression_v46_repeats_speed_after_data_saver_repair() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v46")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.data_saver_on = True
    scaffold.mark_projected_user_tool_actions([("run_speed_test", {})])

    assert scaffold.assistant_requested_user_tool_actions(
        "Data Saver can restrict data performance. Please run:\n"
        "1. `toggle_data_saver_mode` to turn Data Saver OFF\n"
        "2. `run_speed_test`"
    ) == [
        ("toggle_data_saver_mode", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v46_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v46")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.repeat_mobile_data_speed_test_after_terminal_repairs is True
    assert scaffold.require_current_speed_test_for_mobile_data_stop is True


def test_telecom_harness_compression_v47_uses_status_bar_data_saver_icon() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v47")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.observe_tool_output(
        "disconnect_vpn",
        "VPN disconnected successfully. Status Bar: "
        "📶⁴ Excellent | 5G | 📱 Data Enabled | 🔽 Data Saver | 🔋 80%",
    )

    assert scaffold.data_saver_on is True
    assert scaffold.vpn_connected is False
    assert scaffold.projected_mobile_data_recovery_after_speed_failure(
        "Speed Test Result: 55.00 Mbps (Good). "
        "Connection is good for most activities, including HD streaming."
    ) == [
        ("toggle_data_saver_mode", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v47_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v47")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.repeat_mobile_data_speed_test_after_terminal_repairs is True
    assert scaffold.require_current_speed_test_for_mobile_data_stop is True


def test_telecom_harness_compression_v48_prioritizes_mobile_data_terminal_without_refuel() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v48")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.data_saver_on = True
    scaffold.vpn_connected = True

    assert scaffold.mobile_data_terminal_due() is True
    assert scaffold.projected_user_tool_actions() == [
        ("toggle_data_saver_mode", {}),
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v48_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v48")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.repeat_mobile_data_speed_test_after_terminal_repairs is True
    assert scaffold.require_current_speed_test_for_mobile_data_stop is True


def test_telecom_harness_compression_v49_stops_projecting_after_mobile_data_excellent() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v49")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.mobile_data_speed_excellent = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.data_refueled = True

    assert scaffold.projected_user_tool_actions() == []
    assert (
        scaffold.assistant_requested_user_tool_actions(
            "Please run can_send_mms and check_wifi_calling_status."
        )
        == []
    )


def test_tau2_user_projector_loads_v49_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v49")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.repeat_mobile_data_speed_test_after_terminal_repairs is True
    assert scaffold.require_current_speed_test_for_mobile_data_stop is True


def test_telecom_harness_compression_v50_infers_speed_test_tool_output() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v50")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.observe_tool_output(
        "",
        "Speed Test Result: 275.00 Mbps (Excellent). Connection is very fast.",
    )

    assert scaffold.mobile_data_speed_excellent is True
    assert scaffold.projected_user_tool_actions() == []


def test_tau2_user_projector_loads_v50_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v50")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.repeat_mobile_data_speed_test_after_terminal_repairs is True
    assert scaffold.require_current_speed_test_for_mobile_data_stop is True


def test_telecom_harness_compression_v51_preserves_mobile_data_identity_after_refuel() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v51")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = True
    scaffold.vpn_connected = True
    scaffold.observe_tool_output(
        "",
        '{"message": "Successfully added 2.0 GB of data for line L1002 for $4.00", '
        '"new_data_refueling_gb": "2.0", "charge": "4.0"}',
    )
    scaffold.observe_assistant_text(
        "I added 2.0 GB of data. Roaming is enabled, so your mobile data should work. "
        "Please reboot your phone, then run a speed test."
    )

    assert scaffold.mobile_data_issue_active is True
    assert scaffold.mobile_data_terminal_due() is True
    assert scaffold.projected_user_tool_actions() == [
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v51_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v51")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.repeat_mobile_data_speed_test_after_terminal_repairs is True
    assert scaffold.require_current_speed_test_for_mobile_data_stop is True


def test_telecom_harness_compression_v52_refuel_triggers_terminal_without_issue_flag() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v52")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = False
    scaffold.data_refueled = True
    scaffold.data_usage_exceeded = False
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.vpn_connected = True

    assert scaffold.mobile_data_terminal_due() is True
    assert scaffold.projected_user_tool_actions() == [
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v52_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v52")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.repeat_mobile_data_speed_test_after_terminal_repairs is True
    assert scaffold.require_current_speed_test_for_mobile_data_stop is True


def test_telecom_harness_compression_v53_prioritizes_post_refuel_data_saver_terminal() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v53")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_refueled = True
    scaffold.data_usage_exceeded = False
    scaffold.data_saver_on = True
    scaffold.vpn_connected = False
    scaffold.mark_projected_user_tool_actions([("run_speed_test", {})])

    actions = scaffold.assistant_requested_user_tool_actions(
        "I added 2.0 GB of data to line L1002 for $4.00. Your account roaming "
        "and device roaming are enabled, so your mobile data should now work "
        "while you are in France. Please try your mobile data again and run a "
        "speed test on your phone."
    )

    assert actions == [
        ("toggle_data_saver_mode", {}),
        ("run_speed_test", {}),
    ]
    assert ("can_send_mms", {}) not in actions
    assert not any(name == "grant_app_permission" for name, _arguments in actions)


def test_tau2_user_projector_loads_v53_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v53")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_terminal_after_refuel is True
    assert scaffold.repeat_mobile_data_speed_test_after_terminal_repairs is True


def test_telecom_harness_compression_v54_relaxes_refuel_speed_request_due_gate() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v54")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.data_refueled = True
    scaffold.device_roaming_on = True
    scaffold.data_saver_on = True
    scaffold.vpn_connected = False
    scaffold.mark_projected_user_tool_actions([("run_speed_test", {})])

    assert scaffold.mobile_data_terminal_projection_due() is True
    assert scaffold.projected_user_tool_actions() == [
        ("toggle_data_saver_mode", {}),
        ("run_speed_test", {}),
    ]
    scaffold.mark_projected_user_tool_actions([("toggle_data_saver_mode", {})])
    assert scaffold.assistant_requested_user_tool_actions(
        "Please run `run_speed_test` now and tell me the result so we can "
        "confirm whether the mobile internet speed is excellent."
    ) == [
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v54_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v54")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.project_mobile_data_terminal_on_refuel_speed_request is True


def test_telecom_harness_compression_v55_repeats_speed_after_ready_state() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v55")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.mark_projected_user_tool_actions([("run_speed_test", {})])

    assert scaffold.assistant_requested_user_tool_actions(
        "The data-usage check confirms you have not exceeded your plan limit.\n"
        "Please run these phone-side checks/fixes next and send the results:\n"
        "1. `check_data_restriction_status`\n"
        "2. `check_vpn_status`\n"
        "3. `run_speed_test`"
    ) == [("run_speed_test", {})]


def test_tau2_user_projector_loads_v55_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v55")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.repeat_mobile_data_speed_test_after_ready_state is True


def test_telecom_harness_compression_v56_does_not_stop_on_instructional_speed_text() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v56")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert (
        scaffold.terminal_mobile_data_stop_due(
            "Please reboot your device, then run a speed test on mobile data. "
            "If it's still not excellent, tell me the speed test result."
        )
        is False
    )
    assert (
        scaffold.terminal_mobile_data_stop_due(
            "Speed Test Result: 275.00 Mbps (Excellent). Connection is very fast."
        )
        is True
    )


def test_telecom_harness_compression_v56_projects_datasaver_vpn_terminal_repairs() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v56")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.mark_projected_user_tool_actions(
        [
            ("run_speed_test", {}),
            ("check_data_restriction_status", {}),
            ("check_vpn_status", {}),
        ]
    )
    scaffold.observe_tool_output(
        "check_data_restriction_status",
        "Data Saver mode is ON (limits data usage).",
    )
    scaffold.observe_tool_output(
        "check_vpn_status",
        "VPN is ON and connected. Details: {'server_performance': 'poor'}",
    )

    assert scaffold.projected_user_tool_actions() == [
        ("toggle_data_saver_mode", {}),
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v56_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v56")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.repeat_mobile_data_speed_test_after_ready_state is True


def test_telecom_harness_compression_v57_checks_status_before_mms_terminal_speed() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v57")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.mark_projected_user_tool_actions([("run_speed_test", {})])

    assert scaffold.assistant_requested_user_tool_actions(
        "Roaming is enabled successfully. Please run exactly one verification "
        "now: `can_send_mms()` and tell me the result."
    ) == [
        ("check_data_restriction_status", {}),
        ("check_vpn_status", {}),
    ]


def test_telecom_harness_compression_v57_infers_status_outputs_without_names() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v57")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.mark_projected_user_tool_actions(
        [
            ("run_speed_test", {}),
            ("check_data_restriction_status", {}),
            ("check_vpn_status", {}),
        ]
    )
    scaffold.observe_tool_output("", "Data Saver mode is ON (limits data usage).")
    scaffold.observe_tool_output(
        "",
        "VPN is ON and connected. Details: {'server_performance': 'poor'}",
    )

    assert scaffold.projected_user_tool_actions() == [
        ("toggle_data_saver_mode", {}),
        ("disconnect_vpn", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v57_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v57")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.check_mobile_data_status_before_terminal_on_mms_request is True


def test_telecom_harness_compression_v58_requires_actual_mbps_speed_result() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v58")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert (
        scaffold.terminal_mobile_data_stop_due(
            "Fair speed is still below the Excellent target. Please run this "
            "phone-side recovery bundle and report the final speed test result."
        )
        is False
    )
    assert (
        scaffold.terminal_mobile_data_stop_due(
            "Speed Test Result: 275.00 Mbps (Excellent). Connection is very fast."
        )
        is True
    )


def test_telecom_harness_compression_v58_checks_status_before_terminal_speed() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v58")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.mark_projected_user_tool_actions([("run_speed_test", {})])

    assert scaffold.assistant_requested_user_tool_actions(
        "Roaming has been enabled successfully. Please run `run_speed_test` "
        "on your phone and tell me the result so we can confirm whether your "
        "mobile data speed is now Excellent."
    ) == [
        ("check_data_restriction_status", {}),
        ("check_vpn_status", {}),
    ]


def test_tau2_user_projector_loads_v58_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v58")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.check_mobile_data_status_before_terminal_on_mms_request is True


def test_telecom_harness_compression_v59_checks_status_without_terminal_due() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v59")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.mark_projected_user_tool_actions([("run_speed_test", {})])

    assert scaffold.assistant_requested_user_tool_actions(
        "Roaming has been enabled successfully. Please run `run_speed_test` "
        "on your phone and tell me the result so we can confirm whether your "
        "mobile data speed is now Excellent."
    ) == [
        ("check_data_restriction_status", {}),
        ("check_vpn_status", {}),
    ]


def test_tau2_user_projector_loads_v59_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v59")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.check_mobile_data_status_before_terminal_on_mms_request is True


def test_telecom_harness_compression_v60_restores_deferred_safe_speed_test() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v60")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.mark_projected_user_tool_actions([("run_speed_test", {})])

    assert scaffold.assistant_requested_user_tool_actions(
        "Please run `run_speed_test`, `check_data_restriction_status`, "
        "and `check_vpn_status` so we can confirm whether mobile data speed "
        "is Excellent."
    ) == [
        ("check_data_restriction_status", {}),
        ("check_vpn_status", {}),
    ]
    assert scaffold.pending_mobile_data_terminal_speed_after_status_check is True

    scaffold.observe_tool_output("check_data_restriction_status", "Data Saver mode is OFF.")
    scaffold.observe_tool_output("check_vpn_status", "VPN is turned OFF.")

    assert scaffold.assistant_requested_user_tool_actions(
        'Please run `set_network_mode_preference(mode="4g_5g_preferred")`, '
        "then run `run_speed_test` and tell me the result."
    ) == [("run_speed_test", {})]
    assert scaffold.pending_mobile_data_terminal_speed_after_status_check is False


def test_tau2_user_projector_loads_v60_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v60")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.check_mobile_data_status_before_terminal_on_mms_request is True
    assert scaffold.defer_mobile_data_speed_until_status_safe is True


def test_telecom_harness_compression_v61_defers_speed_until_phone_ready() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v61")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    status = (
        "Airplane Mode: OFF\n"
        "SIM Card Status: active\n"
        "Cellular Connection: connected\n"
        "Cellular Signal: poor\n"
        "Cellular Network Type: 2G\n"
        "Mobile Data Enabled: Yes\n"
        "Data Roaming Enabled: No\n"
        "Wi-Fi Radio: OFF\n"
        "Wi-Fi Connected: No\n"
        "VPN Connected"
    )
    scaffold.observe_tool_output("check_network_status", status)

    assert scaffold.assistant_requested_user_tool_actions(status) == [
        ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
        ("reset_apn_settings", {}),
        ("reboot_device", {}),
    ]


def test_tau2_user_projector_loads_v61_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v61")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.check_mobile_data_status_before_terminal_on_mms_request is True
    assert scaffold.defer_mobile_data_speed_until_status_safe is True
    assert scaffold.defer_mobile_data_speed_until_phone_ready is True


def test_telecom_harness_compression_v62_does_not_blind_toggle_unknown_data() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v62")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = False
    scaffold.sim_active = None
    scaffold.mobile_data_on = None
    scaffold.non_2g_network = None
    scaffold.apn_valid = None

    assert scaffold.assistant_requested_user_tool_actions(
        "Please check the phone and mobile data speed."
    ) == [
        ("toggle_airplane_mode", {}),
        ("reseat_sim_card", {}),
        ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
        ("check_apn_settings", {}),
    ]


def test_telecom_harness_compression_v62_toggles_observed_data_off() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v62")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = False
    scaffold.non_2g_network = True
    scaffold.apn_valid = True

    assert scaffold.mobile_data_phone_ready_actions() == [("toggle_data", {})]


def test_tau2_user_projector_loads_v62_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v62")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.defer_mobile_data_speed_until_phone_ready is True
    assert scaffold.toggle_mobile_data_only_when_observed_off is True


def test_telecom_harness_compression_v63_prefers_mobile_terminal_over_mms() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v63")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False

    assert scaffold.projected_user_tool_actions() == [
        ("toggle_roaming", {}),
        ("run_speed_test", {}),
    ]


def test_telecom_harness_compression_v63_preserves_unknown_data_guard() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v63")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = False
    scaffold.sim_active = None
    scaffold.mobile_data_on = None
    scaffold.non_2g_network = None
    scaffold.apn_valid = None

    assert scaffold.mobile_data_phone_ready_actions() == [
        ("toggle_airplane_mode", {}),
        ("reseat_sim_card", {}),
        ("set_network_mode_preference", {"mode": "4g_5g_preferred"}),
        ("check_apn_settings", {}),
    ]


def test_tau2_user_projector_loads_v63_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v63")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.defer_mobile_data_speed_until_phone_ready is True
    assert scaffold.toggle_mobile_data_only_when_observed_off is True
    assert scaffold.prefer_mobile_data_terminal_over_mms_fallback is True


def test_telecom_harness_compression_v64_learns_data_enabled_from_status_bar() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v64")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.observe_tool_output(
        "toggle_airplane_mode",
        "Airplane Mode is now OFF.\nStatus Bar: Excellent | 5G | Data Enabled | Battery 80%",
    )

    assert scaffold.mobile_data_on is True


def test_telecom_harness_compression_v64_blocks_mms_fallback_for_mobile_data() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v64")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False

    assert scaffold.projected_user_tool_actions() == [("run_speed_test", {})]


def test_telecom_harness_compression_v64_waits_instead_of_mms_when_account_due() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v64")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True

    assert scaffold.projected_user_tool_actions() == []


def test_tau2_user_projector_loads_v64_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v64")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.block_mms_fallback_for_mobile_data is True
    assert scaffold.infer_mobile_data_from_status_bar is True


def test_telecom_harness_compression_v65_restores_terminal_bundle_after_status() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v65")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.mark_projected_user_tool_actions([("run_speed_test", {})])

    assert scaffold.assistant_requested_user_tool_actions(
        "Please run `run_speed_test`, `check_data_restriction_status`, "
        "and `check_vpn_status` so we can confirm whether mobile data speed "
        "is Excellent."
    ) == [
        ("check_data_restriction_status", {}),
        ("check_vpn_status", {}),
    ]
    assert scaffold.pending_mobile_data_terminal_speed_after_status_check is True

    scaffold.observe_tool_output("check_data_restriction_status", "Data Saver mode is OFF.")
    scaffold.observe_tool_output("check_vpn_status", "VPN is turned OFF.")

    assert scaffold.assistant_requested_user_tool_actions(
        "Please run `run_speed_test` and tell me the result."
    ) == [
        ("toggle_roaming", {}),
        ("run_speed_test", {}),
    ]
    assert scaffold.pending_mobile_data_terminal_speed_after_status_check is False


def test_tau2_user_projector_loads_v65_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v65")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.restore_full_mobile_terminal_after_status_check is True
    assert scaffold.block_mms_fallback_for_mobile_data is True


def test_telecom_harness_compression_v66_restores_terminal_bundle_after_hydration() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v66")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.data_saver_on = False
    scaffold.vpn_connected = False
    scaffold.pending_mobile_data_terminal_speed_after_status_check = False

    assert scaffold.assistant_requested_user_tool_actions(
        "Please run `run_speed_test` on your phone and tell me the result."
    ) == [
        ("toggle_roaming", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v66_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v66")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.restore_full_mobile_terminal_on_status_safe_request is True
    assert scaffold.block_mms_fallback_for_mobile_data is True


def test_telecom_harness_compression_v67_normalizes_speed_request_to_terminal_bundle() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v67")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = False
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.data_saver_on = False
    scaffold.vpn_connected = False

    assert scaffold.assistant_requested_user_tool_actions(
        "Data Saver and VPN are ruled out, and your account data limit has "
        "not been reached. Please run this diagnostic and send me the result: "
        "`run_speed_test`."
    ) == [
        ("toggle_roaming", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v67_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v67")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.normalize_status_safe_speed_request_to_terminal_bundle is True
    assert scaffold.block_mms_fallback_for_mobile_data is True


def test_telecom_harness_compression_v68_projects_after_observed_roaming_text() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v68")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.active_customer_id = "C1001"
    scaffold.active_phone_number = "555-123-2002"
    scaffold.active_line_id = "L1002"
    scaffold.data_usage_exceeded = False
    scaffold.data_saver_on = False
    scaffold.vpn_connected = False

    actions = _project_user_actions_after_observed_text(
        scaffold,
        (
            "The network status shows airplane mode is off, SIM is active, "
            "cellular is connected with excellent signal on 5G, and mobile data "
            "is enabled. But data roaming is disabled, and I am currently abroad."
        ),
    )

    assert actions == [
        ("toggle_roaming", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v68_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v68")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.normalize_status_safe_speed_request_to_terminal_bundle is True
    assert _post_text_projection_enabled("telecom-mms-prereq-v68") is True
    assert _post_text_projection_enabled("telecom-mms-prereq-v67") is False


def test_telecom_harness_compression_v69_stops_on_nested_speed_tool_message() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v69")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.pending_tool_names.append("run_speed_test")

    scaffold.observe_incoming_message(
        {
            "role": "tool",
            "tool_messages": [
                {
                    "content": (
                        "Speed Test Result: 275.00 Mbps (Excellent). Connection is very fast."
                    ),
                },
            ],
        },
    )

    assert scaffold.current_turn_mobile_data_speed_excellent is True
    assert scaffold.terminal_mobile_data_stop_due("") is True

    scaffold.observe_incoming_message(
        {"role": "assistant", "content": "Great, that should be fixed."},
    )

    assert scaffold.current_turn_mobile_data_speed_excellent is False
    assert scaffold.terminal_mobile_data_stop_due("") is False


def test_tau2_user_projector_loads_v69_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v69")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.require_current_speed_test_for_mobile_data_stop is True
    assert scaffold.block_mms_fallback_for_mobile_data is True
    assert scaffold.normalize_status_safe_speed_request_to_terminal_bundle is True
    assert _post_text_projection_enabled("telecom-mms-prereq-v69") is True


def test_telecom_harness_compression_v70_bundles_unknown_roaming_terminal_repair() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v70")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = None
    scaffold.data_saver_on = True
    scaffold.vpn_connected = False

    actions = scaffold.assistant_requested_user_tool_actions(
        "Yes. Please turn Data Saver mode OFF, then test mobile data again "
        "to see if speed and connectivity improve.",
    )

    assert actions == [
        ("toggle_data_saver_mode", {}),
        ("toggle_roaming", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v70_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v70")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.assume_unknown_phone_roaming_off_for_mobile_data_terminal is True
    assert scaffold.require_current_speed_test_for_mobile_data_stop is True
    assert _post_text_projection_enabled("telecom-mms-prereq-v70") is True


def test_telecom_harness_compression_v71_treats_speed_test_as_terminal_repair_request() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v71")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = None
    scaffold.data_saver_on = True
    scaffold.vpn_connected = False

    actions = scaffold.assistant_requested_user_tool_actions(
        "Turn Data Saver mode OFF, then run a speed test again.",
    )

    assert actions == [
        ("toggle_data_saver_mode", {}),
        ("toggle_roaming", {}),
        ("run_speed_test", {}),
    ]


def test_tau2_user_projector_loads_v71_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v71")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.assume_unknown_phone_roaming_off_for_mobile_data_terminal is True
    assert scaffold.treat_speed_test_as_mobile_data_terminal_repair_request is True
    assert _post_text_projection_enabled("telecom-mms-prereq-v71") is True


def test_telecom_harness_compression_v72_prefers_mobile_data_terminal_over_mms_recovery() -> None:
    scaffold = build_workflow_order_scaffold("telecom-mms-harness-compression-v72")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    scaffold.mobile_data_issue_active = True
    scaffold.airplane_off = True
    scaffold.sim_active = True
    scaffold.mobile_data_on = True
    scaffold.non_2g_network = True
    scaffold.apn_valid = True
    scaffold.account_roaming_enabled = True
    scaffold.device_roaming_on = True
    scaffold.data_saver_on = False
    scaffold.vpn_connected = False

    actions = scaffold.assistant_requested_user_tool_actions(
        "Please run check_wifi_calling_status, grant_app_permission for messaging SMS "
        "and storage, then use can_send_mms."
    )

    assert actions == [("run_speed_test", {})]


def test_tau2_user_projector_loads_v72_profile() -> None:
    scaffold = _user_projector_workflow_order("telecom-mms-prereq-v72")

    assert isinstance(scaffold, TelecomMmsWorkflowOrder)
    assert scaffold.assume_unknown_phone_roaming_off_for_mobile_data_terminal is True
    assert scaffold.treat_speed_test_as_mobile_data_terminal_repair_request is True
    assert _post_text_projection_enabled("telecom-mms-prereq-v72") is True


def test_tau2_user_prompt_appends_crucible_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = ModuleType("tau2.user.user_simulator")
    fake_module.get_global_user_sim_guidelines = lambda use_tools: "Guidelines with tools"
    monkeypatch.setitem(sys.modules, "tau2.user.user_simulator", fake_module)

    prompt = _user_system_prompt(
        "Scenario body",
        use_tools=True,
        append_text="Bundle safe phone actions into one reply.",
    )

    assert "<scenario>" in prompt
    assert "Scenario body" in prompt
    assert "<crucible_user_sim_guard>" in prompt
    assert "Bundle safe phone actions into one reply." in prompt


def test_tau2_route_readiness_rejects_empty_visible_turn() -> None:
    result = SimpleNamespace(text="", termination_reason="completed", rounds=2, tool_calls=[])

    with pytest.raises(RuntimeError, match="route readiness failed"):
        _assert_tau2_route_ready(
            result,
            projected_tool_calls=[],
            role="assistant agent",
        )


def test_tau2_route_readiness_accepts_text_or_projected_tool_call() -> None:
    text_result = SimpleNamespace(text="Done.", termination_reason="completed", rounds=1)
    tool_result = SimpleNamespace(text="", termination_reason="tool_use", rounds=1)

    _assert_tau2_route_ready(text_result, projected_tool_calls=[], role="assistant agent")
    _assert_tau2_route_ready(
        tool_result,
        projected_tool_calls=[object()],
        role="assistant agent",
    )


def test_tau2_codex_empty_text_dump_backstop_detects_new_dump(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("core.paths.GLOBAL_DIAGNOSTICS_DIR", tmp_path)
    dump_dir = tmp_path / "codex-oauth-empty-text"
    dump_dir.mkdir()
    existing = dump_dir / "1-gpt-5.5.json"
    existing.write_text("{}\n")
    before = _codex_empty_text_dumps()

    (dump_dir / "2-gpt-5.5.json").write_text("{}\n")

    with pytest.raises(RuntimeError, match="empty output_text"):
        _raise_on_new_codex_empty_text_dumps(before)


def test_tau2_codex_empty_text_turn_retry_recovers_once() -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self.calls = 0

        async def arun(self, prompt: str) -> SimpleNamespace:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("codex-oauth: empty output_text model=gpt-5.5")
            return SimpleNamespace(text=f"ok:{prompt}")

    loop = FakeLoop()
    state = GeodeTau2State(loop=loop)

    result = _run_geode_turn_with_empty_text_retry(state, "prompt", max_retries=1)

    assert result.text == "ok:prompt"
    assert loop.calls == 2
    assert state.codex_empty_text_retries_used == 1


def test_tau2_codex_empty_text_turn_retry_respects_zero_budget() -> None:
    class FakeLoop:
        async def arun(self, prompt: str) -> None:
            raise RuntimeError(f"codex-oauth: empty output_text prompt={prompt}")

    state = GeodeTau2State(loop=FakeLoop())

    with pytest.raises(RuntimeError, match="empty output_text"):
        _run_geode_turn_with_empty_text_retry(state, "prompt", max_retries=0)

    assert state.codex_empty_text_retries_used == 0


def test_tau2_trajectory_snapshot_paths_sanitize_run_id() -> None:
    trajectory, snapshot = _trajectory_snapshot_paths(
        Path("snapshots"),
        "crucible/tau2 g2 telecom candidate t1",
    )

    assert trajectory == Path("snapshots/crucible-tau2-g2-telecom-candidate-t1.trajectory.json")
    assert snapshot == Path("snapshots/crucible-tau2-g2-telecom-candidate-t1.snapshot.json")


def test_tau2_trajectory_snapshot_writes_copy_and_metadata(tmp_path: Path) -> None:
    harness = tmp_path / "harness"
    run_id = "crucible-tau2-g2-telecom-candidate-t1-openai-sub-gpt55-n2k1-20260706-a"
    results = harness / "data" / "simulations" / run_id / "results.json"
    results.parent.mkdir(parents=True)
    results.write_text('{"simulations": []}\n')

    written = _write_trajectory_snapshot(
        harness_dir=harness,
        snapshot_dir=tmp_path / "snapshots",
        run_id=run_id,
        metadata={"stage": "g2", "agent_guard": "t1"},
    )

    assert written is not None
    trajectory, snapshot = written
    assert trajectory.read_text() == '{"simulations": []}\n'
    assert '"run_id": "crucible-tau2-g2-telecom-candidate-t1' in snapshot.read_text()
    assert '"agent_guard": "t1"' in snapshot.read_text()
