"""NLP agent — voice/text interface for logistics operations."""

from __future__ import annotations

import re
from typing import Any


class NLPAgent:
    """Natural language processing for logistics voice/text commands.

    Parses intents like:
      "Find available trucks near Chicago"
      "What's the rate for a 500-mile load from NYC to Boston?"
      "Show me all overdue shipments"
      "Optimize route for truck TRK-1001"
    """

    INTENTS = {
        r"find|available|nearest.*truck|vehicle": "find_vehicle",
        r"rate|price|cost.*lane|load|shipment": "rate_query",
        r"overdue|late|delay|exception": "anomaly_check",
        r"optimize|route|plan.*truck|vehicle": "route_optimize",
        r"health|status|fleet.*summary": "fleet_health",
        r"forecast|predict|demand|projection": "demand_forecast",
        r"shipment|track|where.*order|load": "track_shipment",
    }

    def __init__(self):
        self._llm = None

    def parse_intent(self, text: str) -> dict[str, Any]:
        text_lower = text.lower().strip()
        for pattern, intent in self.INTENTS.items():
            if re.search(pattern, text_lower):
                entities = self._extract_entities(text)
                return {"intent": intent, "entities": entities, "confidence": 0.85, "raw": text}
        return {"intent": "unknown", "entities": {}, "confidence": 0.1, "raw": text}

    def _extract_entities(self, text: str) -> dict[str, Any]:
        entities = {}
        num_match = re.search(r'(\d+)\s*-*\s*miles?|(\d+)\s*km', text)
        if num_match:
            entities["distance"] = int(num_match.group(1) or num_match.group(2))
        loc_match = re.findall(r'(?:near|from|to|in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', text)
        if loc_match:
            entities["locations"] = loc_match
        truck_match = re.search(r'(TRK-\d+|truck[\s-]*\d+)', text, re.I)
        if truck_match:
            entities["vehicle_id"] = truck_match.group(1)
        weight_match = re.search(r'(\d+)\s*(?:lbs?|kg|pounds?)', text, re.I)
        if weight_match:
            entities["weight"] = int(weight_match.group(1))
        return entities

    async def handle(self, text: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        parsed = self.parse_intent(text)
        intent = parsed["intent"]
        entities = parsed["entities"]

        if intent == "find_vehicle":
            return self._handle_find_vehicle(entities, context or {})
        elif intent == "rate_query":
            return self._handle_rate_query(entities)
        elif intent == "anomaly_check":
            return {"response": "Checking for operational anomalies...", "anomalies": []}
        elif intent == "route_optimize":
            return {"response": f"Optimizing route for {entities.get('vehicle_id', 'fleet')}..."}
        elif intent == "fleet_health":
            return {"response": "Fleet health summary requested."}
        elif intent == "demand_forecast":
            return {"response": "Generating demand forecast..."}
        elif intent == "track_shipment":
            return {"response": f"Tracking shipment..."}
        else:
            return {"response": f"I didn't understand. Try: 'Find available trucks near NYC', 'Rate for 500-mile load', or 'Fleet health'.", "intent": "unknown"}

    def _handle_find_vehicle(self, entities: dict[str, Any], context: dict) -> dict[str, Any]:
        locations = entities.get("locations", [])
        return {"response": f"Searching for available vehicles near {locations[0] if locations else 'your region'}...", "intent": "find_vehicle"}

    def _handle_rate_query(self, entities: dict[str, Any]) -> dict[str, Any]:
        dist = entities.get("distance", 500)
        return {"response": f"Estimated rate for {dist}-mile lane: $1,250 - $1,750 depending on equipment and urgency."}
