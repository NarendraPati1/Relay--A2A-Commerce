class GrowthAgent:
    def __init__(self, inventory: dict, *_, **__):
        self.inventory = inventory

    def propose_action(self, *_args, **_kwargs) -> dict:
        return {
            "status": "idle",
            "reason": "Simple merchant mode only answers catalog requests.",
        }
