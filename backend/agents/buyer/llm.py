import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate


# ============================================================
# LLM CONFIGURATION
# ============================================================

load_dotenv()

llm = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0,
    api_key=os.getenv("GROQ_API_KEY"),
)


# ============================================================
# 1. BUYER INTENT
# ============================================================

class BuyerItem(BaseModel):

    product_query: str

    quantity: int | None = None

    budget: float | None = None

    brand_preference: str | None = None

    pack_size: str | None = None

    constraints: list[str] = Field(
        default_factory=list
    )


class BuyerIntent(BaseModel):

    intent: Literal[
        "search",
        "compare",
        "purchase",
        "modify",
        "cancel",
        "substitute",
        "price_check",
        "availability",
        "order_status",
        "general",
    ]

    # --------------------------------------------------------
    # MULTI-ITEM SUPPORT
    # --------------------------------------------------------

    items: list[BuyerItem] = Field(
        default_factory=list
    )

    next_action: Literal[
        "search",
        "respond",
    ]


buyer_system_prompt = """
You are the Buyer Agent of an agentic commerce system.

Your job is to understand the CUSTOMER request.

You represent the customer.

Analyze the request carefully before producing
structured output.

============================================================
INTENT
============================================================

Classify the request into exactly one of:

search
compare
purchase
modify
cancel
substitute
price_check
availability
order_status
general

============================================================
PRODUCT ITEMS
============================================================

Extract EVERY product the customer is referring to.

Each product must become a separate item.

For example:

"I need Nescafe"

→ items:
[
    {{
        "product_query": "Nescafe"
    }}
]

For:

"Get me Nescafe and Amul milk"

→ items:
[
    {{
        "product_query": "Nescafe"
    }},
    {{
        "product_query": "Amul milk"
    }}
]

For:

"Give me 2 Nescafe and 3 milk"

→ items:
[
    {{
        "product_query": "Nescafe",
        "quantity": 2
    }},
    {{
        "product_query": "milk",
        "quantity": 3
    }}
]

IMPORTANT:

Do NOT combine separate products into one item.

Do NOT invent products.

Preserve the customer's original wording and spelling.

Example:

"do you have nescagfe"

→ product_query = "nescagfe"

Do NOT silently correct spelling.

============================================================
QUANTITY
============================================================

Extract quantity only when explicitly provided.

"give me 3 Nescafe"

→ quantity = 3

"give me some Nescafe"

→ quantity = null

If different products have different quantities,
associate each quantity with the correct product.

============================================================
BUDGET
============================================================

Extract an explicit budget.

"under ₹200"

→ budget = 200

"below 500 rupees"

→ budget = 500

Do not invent a budget.

If the customer gives a total cart budget:

"Get Nescafe and milk under ₹300 total"

Use:

budget = 300

for the overall shopping context only when appropriate.

Do not invent individual product budgets.

============================================================
BRAND
============================================================

Extract explicit brand preferences.

"Nescafe coffee"

→ brand_preference = "Nescafe"

"Amul milk"

→ brand_preference = "Amul"

"any coffee"

→ brand_preference = null

============================================================
PACK SIZE
============================================================

Extract explicit pack sizes.

"Nescafe 100g"

→ pack_size = "100g"

"milk 1L"

→ pack_size = "1L"

============================================================
CONSTRAINTS
============================================================

Extract meaningful explicit customer constraints.

Examples:

"cheapest Nescafe"

→ constraints = ["cheapest"]

"Nescafe under ₹250"

→ constraints = ["under budget"]

"organic coffee"

→ constraints = ["organic"]

If there are no explicit constraints:

→ constraints = []

============================================================
NEXT ACTION
============================================================

Commerce/product-related request:

→ next_action = "search"

Normal conversation:

→ next_action = "respond"

Do not perform the search yourself.

============================================================
IMPORTANT
============================================================

For a multi-item request, extract ALL requested items.

Do not stop after identifying the first product.

Return structured output only.
"""


buyer_prompt = ChatPromptTemplate.from_messages([
    ("system", buyer_system_prompt),
    (
        "human",
        "Customer request:\n\n{user_query}"
    ),
])

buyer_intent_llm = (
    buyer_prompt
    | llm.with_structured_output(BuyerIntent)
)


# ============================================================
# 2. SHOPPING GOAL
# ============================================================

class ShoppingItem(BaseModel):

    product: str

    quantity: int | None = None

    budget: float | None = None

    preferred_brand: str | None = None

    preferred_pack_size: str | None = None

    constraints: list[str] = Field(
        default_factory=list
    )


class ShoppingGoal(BaseModel):

    goal: str

    # --------------------------------------------------------
    # MULTI-ITEM CART
    # --------------------------------------------------------

    items: list[ShoppingItem] = Field(
        default_factory=list
    )

    optimization_priority: Literal[
        "lowest_price",
        "best_value",
        "availability",
        "preference_match",
        "balanced",
    ]


shopping_goal_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
You are the Shopping Goal component of a Buyer Agent.

Convert the customer's request and buyer understanding
into a clear shopping objective.

The goal should represent WHAT THE CUSTOMER IS TRYING
TO ACHIEVE.

============================================================
ITEMS
============================================================

Create one ShoppingItem for every requested product.

Preserve the information extracted by the Buyer Intent.

Do not combine different products.

Do not invent products.

For example:

Customer:

"Get me Nescafe and Amul milk"

Buyer understanding:

items = [
    {{
        "product_query": "Nescafe"
    }},
    {{
        "product_query": "Amul milk"
    }}
]

Shopping goal:

items = [
    {{
        "product": "Nescafe"
    }},
    {{
        "product": "Amul milk"
    }}
]

============================================================
CONSIDER
============================================================

For every item consider:

- product
- quantity
- budget
- brand preference
- pack size
- constraints

Also determine the overall optimization priority.

============================================================
OPTIMIZATION PRIORITY
============================================================

lowest_price
→ customer explicitly wants cheapest/lowest price

best_value
→ customer cares about value/deal

availability
→ customer mainly wants something available

preference_match
→ explicit brand, pack size, merchant, or other
preference is most important

balanced
→ no single priority dominates

============================================================
IMPORTANT
============================================================

Do not invent preferences.

Only use information provided by the customer
or buyer understanding.

Personalization may later modify this goal.

Do not invent personalization.

Give a concise goal description.

Return structured output only.
"""
    ),
    (
        "human",
        """
CUSTOMER REQUEST:
{user_query}

BUYER UNDERSTANDING:
{buyer_intent}

PERSONALIZED PREFERENCES:
{personalized_preferences}
"""
    ),
])

shopping_goal_llm = (
    shopping_goal_prompt
    | llm.with_structured_output(ShoppingGoal)
)


# ============================================================
# 3. OFFER NORMALIZATION
# ============================================================

class NormalizedOffer(BaseModel):

    merchant: str

    product_name: str

    available: bool

    price: float | None = None

    stock: int | None = None

    currency: str = "INR"


offer_normalization_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
You are the Offer Normalization component of a Buyer Agent.

Convert a merchant's natural-language response
into structured offer information.

Extract ONLY information explicitly present.

Do NOT invent information.

FIELDS
------

merchant:
Merchant providing the response.

product_name:
Expected product being checked.

available:
Whether the merchant says the product is available.

price:
Explicit product price.
If absent, return null.

stock:
Explicit stock quantity.
If absent, return null.

currency:
Use INR when the merchant uses ₹ or Indian rupees.

IMPORTANT
---------

Never infer price or stock.

Return only structured output.
"""
    ),
    (
        "human",
        """
MERCHANT:
{merchant}

EXPECTED PRODUCT:
{product_name}

MERCHANT RESPONSE:
{response}
"""
    ),
])

offer_normalizer_llm = (
    offer_normalization_prompt
    | llm.with_structured_output(NormalizedOffer)
)


# ============================================================
# 4. RELEVANCE GUARD
# ============================================================

class RelevanceCheck(BaseModel):

    is_relevant: bool

    relevance_score: float = Field(
        ge=0.0,
        le=1.0,
    )

    reasoning: str


relevance_guard_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
You are the Product Relevance Guard of a Buyer Agent.

Your job is to determine whether a retrieved product candidate
is relevant to the customer's shopping request.

A candidate is RELEVANT when it:

- directly matches the requested product
- matches the requested category
- matches the requested brand
- matches the requested pack size
- or is a reasonable semantic interpretation of the request

A candidate is NOT RELEVANT when it is merely vaguely similar.

Examples:

Customer: "I want coffee"
Candidate: "Nescafe Classic 100g"
→ relevant

Customer: "I want coffee"
Candidate: "Local Filter Coffee 250g"
→ relevant

Customer: "I want chocolate"
Candidate: "Amul Taaza Milk 1L"
→ not relevant

Customer: "I want chocolate"
Candidate: "Nescafe Classic 100g"
→ not relevant

IMPORTANT
---------

Do not invent products.

Do not modify the candidate.

Use the shopping goal and candidate information together.

Return:

- is_relevant
- relevance_score between 0 and 1
- concise reasoning

Do not expose chain-of-thought.
"""
    ),
    (
        "human",
        """
CUSTOMER REQUEST:
{user_query}

SHOPPING GOAL:
{shopping_goal}

PRODUCT CANDIDATE:
{candidate}
"""
    ),
])

relevance_guard_llm = (
    relevance_guard_prompt
    | llm.with_structured_output(RelevanceCheck)
)


# ============================================================
# 5. EVALUATE OPTIONS
# ============================================================

class OptionEvaluation(BaseModel):

    selected_offer_index: int | None = None

    reasoning: str

    needs_clarification: bool = False


option_evaluation_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
You are the Evaluation component of a Buyer Agent.

You represent the CUSTOMER.

The system has already removed offers that violate
hard constraints and irrelevant products.

Choose the BEST offer from the VALID OFFERS.

Consider:

- customer preferences
- preferred brand
- preferred pack size
- optimization priority
- price
- stock
- product relevance
- overall value

OPTIMIZATION PRIORITY
---------------------

lowest_price:
Choose the lowest priced valid offer.

best_value:
Consider price, product and preferences together.

availability:
Prefer strong availability and sufficient stock.

preference_match:
Prefer the strongest match to explicit preferences.

balanced:
Make the best overall choice.

IMPORTANT
---------

ONLY choose from VALID OFFERS.

Never choose a rejected offer.

Never invent information.

The selected_offer_index refers to the position
in VALID OFFERS, starting from 0.

If there are no valid offers:

selected_offer_index = null

Do not expose chain-of-thought.

Return concise reasoning only.
"""
    ),
    (
        "human",
        """
CUSTOMER REQUEST:
{user_query}

SHOPPING GOAL:
{shopping_goal}

PERSONALIZED PREFERENCES:
{personalized_preferences}

VALID OFFERS:
{valid_offers}

Select the best valid offer.
"""
    ),
])

option_evaluator_llm = (
    option_evaluation_prompt
    | llm.with_structured_output(OptionEvaluation)
)


# ============================================================
# 6. SUBSTITUTION DECISION
# ============================================================

class SubstitutionDecision(BaseModel):

    should_substitute: bool

    reasoning: str


substitution_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
You are the Substitution Decision component of a Buyer Agent.

Determine whether the customer should be offered
a substitute product.

Consider substitution when:

- no valid merchant offer satisfies the shopping goal
- suitable alternative products exist in the retrieved
  product candidates

Do NOT substitute when:

- the customer explicitly requires the exact product
- no reasonable alternative exists

Never invent products.

Only consider products contained in the candidates.

Return concise reasoning.

Do not expose chain-of-thought.
"""
    ),
    (
        "human",
        """
CUSTOMER REQUEST:
{user_query}

SHOPPING GOAL:
{shopping_goal}

RETRIEVED PRODUCT CANDIDATES:
{product_candidates}

REJECTED OFFERS:
{rejected_offers}

Should substitution be attempted?
"""
    ),
])

substitution_decision_llm = (
    substitution_prompt
    | llm.with_structured_output(SubstitutionDecision)
)


# ============================================================
# 7. GENERAL RESPONSE
# ============================================================

# ============================================================
# 8. SUBSTITUTE PRODUCT SELECTION
# ============================================================

class SubstituteSelection(BaseModel):

    selected_product_index: int | None = None

    reasoning: str


substitute_selection_prompt = ChatPromptTemplate.from_messages([
    (
        "system",
        """
You are the Substitute Product Selection component
of a Buyer Agent.

The customer's original request could not be satisfied.

Choose the BEST substitute from the provided product candidates.

A good substitute should:

- belong to the same or closely related category
- satisfy the customer's original intent
- respect explicit brand or pack preferences when possible
- remain within the customer's constraints when possible

IMPORTANT:

Only select from the provided candidates.

Do not invent products.

Do not select the original product if it has already failed
because of availability.

If no reasonable substitute exists:

selected_product_index = null

Return concise reasoning only.

Do not expose chain-of-thought.
"""
    ),
    (
        "human",
        """
CUSTOMER REQUEST:
{user_query}

SHOPPING GOAL:
{shopping_goal}

PRODUCT CANDIDATES:
{product_candidates}

REJECTED OFFERS:
{rejected_offers}

Select the best substitute.
"""
    ),
])

substitute_selector_llm = (
    substitute_selection_prompt
    | llm.with_structured_output(SubstituteSelection)
)
