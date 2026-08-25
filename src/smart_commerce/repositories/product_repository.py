import json
from pathlib import Path

from smart_commerce.models.schemas import Product


class ProductRepository:
    def __init__(self, data_path: Path | None = None) -> None:
        self.data_path = data_path or Path(__file__).resolve().parents[3] / "data" / "products.json"
        self._products: list[Product] | None = None

    def list_products(
        self,
        *,
        max_price: float | None = None,
        category: str | None = None,
        keyword: str | None = None,
    ) -> list[Product]:
        products = self._load()
        normalized_keyword = (keyword or "").strip().lower()
        normalized_category = (category or "").strip().lower()
        result = [
            product
            for product in products
            if (max_price is None or product.price <= max_price)
            and (not normalized_category or product.category.lower() == normalized_category)
            and (
                not normalized_keyword
                or normalized_keyword in product.name.lower()
                or normalized_keyword in product.description.lower()
                or any(normalized_keyword in tag.lower() for tag in product.tags)
            )
        ]
        return sorted(result, key=lambda product: (-product.rating, product.price))

    def _load(self) -> list[Product]:
        if self._products is None:
            with self.data_path.open("r", encoding="utf-8") as file:
                self._products = [Product.model_validate(item) for item in json.load(file)]
        return self._products
