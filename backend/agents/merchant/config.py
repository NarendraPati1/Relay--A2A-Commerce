from copy import deepcopy


MERCHANTS = {
    "dmart": {
        "id": "dmart",
        "name": "DMart",
        "port": 9000,
        "inventory": {
            "Nescafe Classic 100g": {
                "price": 210,
                "stock": 10,
            },
            "Amul Taaza Milk 1L": {
                "price": 65,
                "stock": 20,
            },
        },
    },
    "reliance": {
        "id": "reliance",
        "name": "Reliance",
        "port": 9001,
        "inventory": {
            "Nescafe Classic 100g": {
                "price": 205,
                "stock": 8,
            },
            "Amul Taaza Milk 1L": {
                "price": 68,
                "stock": 15,
            },
        },
    },
    "localmart": {
        "id": "localmart",
        "name": "LocalMart",
        "port": 9002,
        "inventory": {
            "Nescafe Classic 100g": {
                "price": 215,
                "stock": 12,
            },
            "Local Filter Coffee 250g": {
                "price": 180,
                "stock": 6,
            },
        },
    },
}


def get_merchant_config(merchant_id: str) -> dict:
    try:
        return deepcopy(MERCHANTS[merchant_id])
    except KeyError as error:
        valid = ", ".join(sorted(MERCHANTS))
        raise ValueError(
            f"Unknown merchant '{merchant_id}'. Choose one of: {valid}."
        ) from error
