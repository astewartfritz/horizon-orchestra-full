from __future__ import annotations

import random
from typing import Any


class WebShopEnv:
    """Simplified text-based WebShop environment (OpenAI gym-style)."""

    def __init__(self, seed: int | None = None, max_steps: int = 30):
        self.max_steps = max_steps
        self.rng = random.Random(seed)
        self.instruction = ""
        self.products: list[dict[str, Any]] = []
        self.actions_taken: list[str] = []
        self.page = "search"
        self.search_query = ""
        self.viewing_product: dict | None = None
        self.cart: list[dict] = []
        self.step_count = 0
        self.done = False

    def reset(self, instruction: str) -> str:
        self.instruction = instruction
        self.actions_taken = []
        self.page = "search"
        self.search_query = ""
        self.viewing_product = None
        self.cart = []
        self.step_count = 0
        self.done = False
        self.products = self._generate_products()
        return self._get_obs()

    def _generate_products(self) -> list[dict[str, Any]]:
        products = []
        categories = ["electronics", "home", "clothing", "books", "sports"]
        for i in range(12):
            cat = self.rng.choice(categories)
            price = round(self.rng.uniform(10, 500), 2)
            rating = round(self.rng.uniform(3.0, 5.0), 1)
            products.append({
                "id": i,
                "title": f"{cat.title()} Product {i} - {self.rng.choice(['Premium','Basic','Pro','Lite','Deluxe'])}",
                "price": price,
                "rating": rating,
                "category": cat,
                "attributes": {
                    "color": self.rng.choice(["black", "white", "red", "blue"]),
                    "size": self.rng.choice(["S", "M", "L", "XL"]),
                    "brand": self.rng.choice(["BrandA", "BrandB", "BrandC"]),
                },
                "description": f"A {cat.lower()} product with {rating} star rating at ${price:.2f}.",
            })
        return products

    def step(self, action: str) -> tuple[str, float, bool, dict]:
        self.step_count += 1
        self.actions_taken.append(action)
        reward = 0.0
        info: dict[str, Any] = {"action": action}

        if self.page == "search":
            if action.startswith("search["):
                self.search_query = action[7:-1]
                results = [p for p in self.products if self.search_query.lower() in p["title"].lower() or self.search_query.lower() in p["category"].lower()]
                self.page = "results"
                info["results_count"] = len(results)
                obs = self._render_results(results)
            else:
                obs = self._get_obs()
        elif self.page == "results":
            if action.startswith("click["):
                idx = int(action[6:-1])
                if 0 <= idx < len(self.products):
                    self.viewing_product = self.products[idx]
                    self.page = "product"
                    obs = self._render_product(self.viewing_product)
                else:
                    obs = self._get_obs()
            elif action == "back":
                self.page = "search"
                obs = self._get_obs()
            else:
                obs = self._get_obs()
        elif self.page == "product":
            if action == "add_to_cart":
                if self.viewing_product:
                    self.cart.append(self.viewing_product)
                self.page = "cart"
                obs = self._render_cart()
            elif action == "back":
                self.page = "results"
                self.viewing_product = None
                obs = self._get_obs()
            else:
                obs = self._get_obs()
        elif self.page == "cart":
            if action == "purchase":
                reward = self._compute_reward()
                self.done = True
                info["purchased"] = len(self.cart)
                info["reward"] = reward
                obs = f"Purchase complete! Reward: {reward:.2f}"
            elif action == "back":
                self.page = "product"
                obs = self._render_product(self.viewing_product)
            else:
                obs = self._get_obs()
        else:
            obs = self._get_obs()

        if self.step_count >= self.max_steps:
            self.done = True
            if not reward:
                reward = self._compute_reward() * 0.5

        return obs, reward, self.done, info

    def _compute_reward(self) -> float:
        if not self.cart:
            return -1.0
        attrs = self.instruction.lower()
        score = 0.0
        for p in self.cart:
            if p["category"].lower() in attrs:
                score += 0.5
            if str(p["price"]) in attrs:
                score += 0.3
            if p["attributes"]["brand"].lower() in attrs:
                score += 0.2
            if p["attributes"]["color"] in attrs:
                score += 0.2
        score += 0.5 * (len(self.cart) > 0)
        score -= 0.1 * max(0, len(self.actions_taken) - 5)
        return max(-2.0, min(2.0, score))

    def _get_obs(self) -> str:
        return f"Search page (step {self.step_count}). Instruction: {self.instruction}. Enter a search query."

    def _render_results(self, results: list[dict]) -> str:
        if not results:
            return "No results found. Try a different search."
        lines = [f"Search results for '{self.search_query}':"]
        for i, p in enumerate(results[:6]):
            lines.append(f"  [{i}] {p['title']} — ${p['price']:.2f} — rating: {p['rating']}")
        lines.append("Actions: click[N] to view, back to search")
        return "\n".join(lines)

    def _render_product(self, p: dict) -> str:
        return (
            f"Product: {p['title']}\n"
            f"Price: ${p['price']:.2f}\n"
            f"Rating: {p['rating']}/5.0\n"
            f"Category: {p['category']}\n"
            f"Description: {p['description']}\n"
            f"Actions: add_to_cart, back"
        )

    def _render_cart(self) -> str:
        if not self.cart:
            return "Cart is empty. Actions: back"
        lines = ["Cart items:"]
        for p in self.cart:
            lines.append(f"  - {p['title']} — ${p['price']:.2f}")
        lines.append("Actions: purchase, back")
        return "\n".join(lines)

    def get_available_actions(self) -> list[str]:
        if self.page == "search":
            return ["search[<query>]"]
        elif self.page == "results":
            return [f"click[{i}]" for i in range(min(6, len(self.products)))] + ["back"]
        elif self.page == "product":
            return ["add_to_cart", "back"]
        elif self.page == "cart":
            return ["purchase", "back"]
        return []

    def close(self) -> None:
        pass
