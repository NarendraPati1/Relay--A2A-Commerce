from copy import deepcopy


# Demo-market configuration. A production deployment should load the same
# shape from merchant onboarding/storage rather than this local fixture.
MERCHANTS = {
    "dmart": {"id": "dmart", "name": "DMart", "port": 9000, "discount_rules": [(3, 4), (10, 8)], "recommendation_policy": {"Nescafe Classic 100g": {"cross_sell": ["Amul Taaza Milk 1L"], "upsell": ["BRU Gold Instant Coffee 100g"]}}, "inventory": {
        "Nescafe Classic 100g": {"price": 210, "stock": 30}, "BRU Gold Instant Coffee 100g": {"price": 195, "stock": 20}, "Amul Taaza Milk 1L": {"price": 65, "stock": 40}, "Cadbury Dairy Milk 50g": {"price": 45, "stock": 50}, "Tata Tea Gold 250g": {"price": 155, "stock": 25}, "India Gate Basmati Rice 1kg": {"price": 125, "stock": 35}, "Fortune Sunflower Oil 1L": {"price": 148, "stock": 30}, "Maggi 2-Minute Noodles 280g": {"price": 68, "stock": 45},
    }},
    "reliance": {"id": "reliance", "name": "Reliance Smart", "port": 9001, "discount_rules": [(3, 5), (8, 9)], "recommendation_policy": {"Nescafe Classic 100g": {"cross_sell": ["Amul Taaza Milk 1L"], "upsell": ["Tata Coffee Grand 100g"]}}, "inventory": {
        "Nescafe Classic 100g": {"price": 205, "stock": 28}, "Tata Coffee Grand 100g": {"price": 220, "stock": 18}, "Amul Taaza Milk 1L": {"price": 68, "stock": 35}, "Amul Lactose Free Milk 1L": {"price": 92, "stock": 14}, "Cadbury Bournville Dark Chocolate 80g": {"price": 105, "stock": 25}, "Nestle KitKat 38g": {"price": 28, "stock": 60}, "Aashirvaad Whole Wheat Atta 5kg": {"price": 295, "stock": 22}, "Tata Salt 1kg": {"price": 28, "stock": 50},
    }},
    "localmart": {"id": "localmart", "name": "LocalMart", "port": 9002, "discount_rules": [(2, 3), (6, 7)], "recommendation_policy": {"Local Filter Coffee 250g": {"cross_sell": ["Mother Dairy Full Cream Milk 1L"], "upsell": ["Nescafe Classic 100g"]}}, "inventory": {
        "Nescafe Classic 100g": {"price": 215, "stock": 20}, "Local Filter Coffee 250g": {"price": 180, "stock": 16}, "Mother Dairy Full Cream Milk 1L": {"price": 72, "stock": 24}, "Cadbury Dairy Milk 50g": {"price": 48, "stock": 32}, "Brooke Bond Red Label 250g": {"price": 130, "stock": 18}, "Quaker Oats 1kg": {"price": 185, "stock": 15}, "Maggi 2-Minute Noodles 280g": {"price": 70, "stock": 36},
    }},
    "freshbasket": {"id": "freshbasket", "name": "FreshBasket", "port": 9003, "discount_rules": [(3, 6), (10, 10)], "recommendation_policy": {"BRU Gold Instant Coffee 100g": {"cross_sell": ["Mother Dairy Full Cream Milk 1L"], "upsell": ["Tata Coffee Grand 100g"]}}, "inventory": {
        "BRU Gold Instant Coffee 100g": {"price": 188, "stock": 24}, "Tata Coffee Grand 100g": {"price": 212, "stock": 20}, "Amul Lactose Free Milk 1L": {"price": 89, "stock": 18}, "Mother Dairy Full Cream Milk 1L": {"price": 70, "stock": 30}, "Cadbury Dairy Milk 50g": {"price": 43, "stock": 45}, "Tata Tea Gold 250g": {"price": 150, "stock": 28}, "India Gate Basmati Rice 1kg": {"price": 120, "stock": 40}, "Quaker Oats 1kg": {"price": 178, "stock": 18},
    }},
    "quickcart": {"id": "quickcart", "name": "QuickCart", "port": 9004, "discount_rules": [(2, 2), (5, 6)], "recommendation_policy": {"Nescafe Classic 100g": {"cross_sell": ["Amul Taaza Milk 1L"], "upsell": []}}, "inventory": {
        "Nescafe Classic 100g": {"price": 208, "stock": 15}, "Amul Taaza Milk 1L": {"price": 66, "stock": 25}, "Amul Lactose Free Milk 1L": {"price": 95, "stock": 12}, "Nestle KitKat 38g": {"price": 26, "stock": 70}, "Cadbury Bournville Dark Chocolate 80g": {"price": 99, "stock": 20}, "Fortune Sunflower Oil 1L": {"price": 145, "stock": 25}, "Aashirvaad Whole Wheat Atta 5kg": {"price": 288, "stock": 18}, "Tata Salt 1kg": {"price": 26, "stock": 55},
    }},
}


def get_merchant_config(merchant_id: str) -> dict:
    try:
        return deepcopy(MERCHANTS[merchant_id])
    except KeyError as error:
        valid = ", ".join(sorted(MERCHANTS))
        raise ValueError(f"Unknown merchant '{merchant_id}'. Choose one of: {valid}.") from error
