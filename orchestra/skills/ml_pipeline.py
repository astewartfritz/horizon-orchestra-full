"""ML Pipeline skill — feature engineering, model training, evaluation.

Generates scikit-learn code for classification, regression, clustering,
and feature importance analysis.
"""

from __future__ import annotations

import json, logging, textwrap
from typing import Any
from .base import Skill, run_code_in_sandbox

__all__ = ["MLPipelineSkill"]
log = logging.getLogger("orchestra.skills.ml_pipeline")


class MLPipelineSkill(Skill):
    name = "ml_pipeline"
    description = "Train, evaluate, and compare ML models: classification, regression, clustering, feature importance."

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        dispatch = {
            "ml_classify": self._classify, "ml_regress": self._regress,
            "ml_cluster": self._cluster, "ml_feature_importance": self._importance,
            "ml_auto_select": self._auto_select,
        }
        handler = dispatch.get(action)
        return await handler(params) if handler else {"error": f"Unknown: {action}"}

    async def _classify(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        target = params.get("target", "")
        features = params.get("features", [])
        model_type = params.get("model", "random_forest")
        if not all([fp, target]):
            return {"error": "file_path and target required"}
        feat_code = f"[{', '.join(repr(f) for f in features)}]" if features else "None"
        code = textwrap.dedent(f"""\
            import pandas as pd, json, numpy as np
            from sklearn.model_selection import train_test_split, cross_val_score
            from sklearn.preprocessing import LabelEncoder, StandardScaler
            from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, classification_report
            from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
            from sklearn.linear_model import LogisticRegression
            from sklearn.svm import SVC

            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            feat_cols = {feat_code}
            if feat_cols is None:
                feat_cols = [c for c in df.columns if c != "{target}"]
            df_clean = df[feat_cols + ["{target}"]].dropna()

            # Encode categoricals
            le_map = {{}}
            for c in df_clean.select_dtypes(include=["object"]).columns:
                le = LabelEncoder()
                df_clean[c] = le.fit_transform(df_clean[c].astype(str))
                le_map[c] = list(le.classes_)

            X, y = df_clean[feat_cols], df_clean["{target}"]
            X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y if len(y.unique()) < 50 else None)

            scaler = StandardScaler()
            X_tr_s, X_te_s = scaler.fit_transform(X_tr), scaler.transform(X_te)

            models = {{"random_forest": RandomForestClassifier(n_estimators=100, random_state=42), "gradient_boosting": GradientBoostingClassifier(n_estimators=100, random_state=42), "logistic_regression": LogisticRegression(max_iter=1000, random_state=42)}}
            m = models.get("{model_type}", models["random_forest"])
            m.fit(X_tr_s, y_tr)
            pred = m.predict(X_te_s)
            cv = cross_val_score(m, X_tr_s, y_tr, cv=5)

            print(json.dumps({{
                "model": "{model_type}", "target": "{target}", "features": feat_cols,
                "accuracy": round(float(accuracy_score(y_te, pred)), 4),
                "precision": round(float(precision_score(y_te, pred, average="weighted", zero_division=0)), 4),
                "recall": round(float(recall_score(y_te, pred, average="weighted", zero_division=0)), 4),
                "f1": round(float(f1_score(y_te, pred, average="weighted", zero_division=0)), 4),
                "cv_mean": round(float(cv.mean()), 4), "cv_std": round(float(cv.std()), 4),
                "n_train": len(X_tr), "n_test": len(X_te), "n_classes": int(y.nunique()),
            }}))
        """)
        return await run_code_in_sandbox(code, timeout=120)

    async def _regress(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        target = params.get("target", "")
        features = params.get("features", [])
        model_type = params.get("model", "random_forest")
        if not all([fp, target]):
            return {"error": "file_path and target required"}
        feat_code = f"[{', '.join(repr(f) for f in features)}]" if features else "None"
        code = textwrap.dedent(f"""\
            import pandas as pd, json, numpy as np
            from sklearn.model_selection import train_test_split, cross_val_score
            from sklearn.preprocessing import StandardScaler, LabelEncoder
            from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
            from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
            from sklearn.linear_model import LinearRegression, Ridge, Lasso

            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            feat_cols = {feat_code}
            if feat_cols is None:
                feat_cols = [c for c in df.select_dtypes(include=[np.number]).columns if c != "{target}"]
            df_clean = df[feat_cols + ["{target}"]].dropna()
            for c in df_clean.select_dtypes(include=["object"]).columns:
                df_clean[c] = LabelEncoder().fit_transform(df_clean[c].astype(str))

            X, y = df_clean[feat_cols], df_clean["{target}"]
            X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)
            scaler = StandardScaler()
            X_tr_s, X_te_s = scaler.fit_transform(X_tr), scaler.transform(X_te)

            models = {{"random_forest": RandomForestRegressor(n_estimators=100, random_state=42), "gradient_boosting": GradientBoostingRegressor(n_estimators=100, random_state=42), "linear": LinearRegression(), "ridge": Ridge(), "lasso": Lasso()}}
            m = models.get("{model_type}", models["random_forest"])
            m.fit(X_tr_s, y_tr)
            pred = m.predict(X_te_s)

            print(json.dumps({{
                "model": "{model_type}", "target": "{target}", "features": feat_cols,
                "r2_train": round(float(m.score(X_tr_s, y_tr)), 4),
                "r2_test": round(float(r2_score(y_te, pred)), 4),
                "rmse": round(float(mean_squared_error(y_te, pred)**0.5), 4),
                "mae": round(float(mean_absolute_error(y_te, pred)), 4),
                "n_train": len(X_tr), "n_test": len(X_te),
            }}))
        """)
        return await run_code_in_sandbox(code, timeout=120)

    async def _cluster(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        n_clusters = params.get("n_clusters", 3)
        features = params.get("features", [])
        if not fp:
            return {"error": "file_path required"}
        feat_code = f"[{', '.join(repr(f) for f in features)}]" if features else "None"
        code = textwrap.dedent(f"""\
            import pandas as pd, json, numpy as np
            from sklearn.cluster import KMeans
            from sklearn.preprocessing import StandardScaler
            from sklearn.metrics import silhouette_score

            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            feat_cols = {feat_code}
            if feat_cols is None:
                feat_cols = list(df.select_dtypes(include=[np.number]).columns)
            X = df[feat_cols].dropna()
            scaler = StandardScaler()
            X_s = scaler.fit_transform(X)

            km = KMeans(n_clusters={n_clusters}, random_state=42, n_init=10)
            labels = km.fit_predict(X_s)
            sil = silhouette_score(X_s, labels)

            cluster_sizes = pd.Series(labels).value_counts().sort_index().to_dict()
            centers = {{i: dict(zip(feat_cols, [round(float(v), 4) for v in c])) for i, c in enumerate(scaler.inverse_transform(km.cluster_centers_))}}

            print(json.dumps({{
                "n_clusters": {n_clusters}, "features": feat_cols,
                "silhouette_score": round(float(sil), 4),
                "inertia": round(float(km.inertia_), 2),
                "cluster_sizes": {{str(k): int(v) for k, v in cluster_sizes.items()}},
                "cluster_centers": centers, "n_samples": len(X),
            }}))
        """)
        return await run_code_in_sandbox(code, timeout=120)

    async def _importance(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        target = params.get("target", "")
        if not all([fp, target]):
            return {"error": "file_path and target required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json, numpy as np
            from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
            from sklearn.preprocessing import LabelEncoder

            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            feat_cols = [c for c in df.columns if c != "{target}"]
            df_clean = df[feat_cols + ["{target}"]].dropna()
            for c in df_clean.select_dtypes(include=["object"]).columns:
                df_clean[c] = LabelEncoder().fit_transform(df_clean[c].astype(str))

            X, y = df_clean[feat_cols], df_clean["{target}"]
            is_class = y.nunique() < 20
            m = (RandomForestClassifier if is_class else RandomForestRegressor)(n_estimators=100, random_state=42)
            m.fit(X, y)

            imp = sorted(zip(feat_cols, m.feature_importances_), key=lambda x: x[1], reverse=True)
            print(json.dumps({{
                "target": "{target}", "task": "classification" if is_class else "regression",
                "features": [
                    {{"name": n, "importance": round(float(v), 6), "rank": i + 1}}
                    for i, (n, v) in enumerate(imp)
                ],
                "cumulative_top5": round(float(sum(v for _, v in imp[:5])), 4),
            }}))
        """)
        return await run_code_in_sandbox(code, timeout=120)

    async def _auto_select(self, params: dict[str, Any]) -> dict[str, Any]:
        fp = params.get("file_path", "")
        target = params.get("target", "")
        if not all([fp, target]):
            return {"error": "file_path and target required"}
        code = textwrap.dedent(f"""\
            import pandas as pd, json, numpy as np, warnings
            warnings.filterwarnings("ignore")
            from sklearn.model_selection import cross_val_score
            from sklearn.preprocessing import LabelEncoder, StandardScaler
            from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor, GradientBoostingClassifier, GradientBoostingRegressor
            from sklearn.linear_model import LogisticRegression, LinearRegression, Ridge
            from sklearn.svm import SVC, SVR

            df = pd.read_csv("{fp}") if "{fp}".endswith(".csv") else pd.read_parquet("{fp}")
            feat_cols = [c for c in df.columns if c != "{target}"]
            df_clean = df[feat_cols + ["{target}"]].dropna()
            for c in df_clean.select_dtypes(include=["object"]).columns:
                df_clean[c] = LabelEncoder().fit_transform(df_clean[c].astype(str))
            X, y = df_clean[feat_cols], df_clean["{target}"]
            X_s = StandardScaler().fit_transform(X)

            is_class = y.nunique() < 20
            if is_class:
                candidates = {{"RandomForest": RandomForestClassifier(n_estimators=50, random_state=42), "GradientBoosting": GradientBoostingClassifier(n_estimators=50, random_state=42), "LogisticRegression": LogisticRegression(max_iter=500, random_state=42)}}
                scoring = "accuracy"
            else:
                candidates = {{"RandomForest": RandomForestRegressor(n_estimators=50, random_state=42), "GradientBoosting": GradientBoostingRegressor(n_estimators=50, random_state=42), "Ridge": Ridge(), "Linear": LinearRegression()}}
                scoring = "r2"

            results = []
            for name, model in candidates.items():
                cv = cross_val_score(model, X_s, y, cv=5, scoring=scoring)
                results.append({{"model": name, "cv_mean": round(float(cv.mean()), 4), "cv_std": round(float(cv.std()), 4)}})
            results.sort(key=lambda x: x["cv_mean"], reverse=True)

            print(json.dumps({{
                "task": "classification" if is_class else "regression",
                "target": "{target}", "scoring": scoring,
                "results": results, "best_model": results[0]["model"],
                "n_samples": len(X), "n_features": len(feat_cols),
            }}))
        """)
        return await run_code_in_sandbox(code, timeout=180)

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        return [
            {"type": "function", "function": {"name": "ml_classify", "description": "Train a classification model (random_forest, gradient_boosting, logistic_regression).", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "target": {"type": "string"}, "features": {"type": "array", "items": {"type": "string"}}, "model": {"type": "string", "enum": ["random_forest", "gradient_boosting", "logistic_regression"]}}, "required": ["file_path", "target"]}}},
            {"type": "function", "function": {"name": "ml_regress", "description": "Train a regression model (random_forest, gradient_boosting, linear, ridge, lasso).", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "target": {"type": "string"}, "features": {"type": "array", "items": {"type": "string"}}, "model": {"type": "string", "enum": ["random_forest", "gradient_boosting", "linear", "ridge", "lasso"]}}, "required": ["file_path", "target"]}}},
            {"type": "function", "function": {"name": "ml_cluster", "description": "K-Means clustering with silhouette scoring.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "n_clusters": {"type": "integer"}, "features": {"type": "array", "items": {"type": "string"}}}, "required": ["file_path"]}}},
            {"type": "function", "function": {"name": "ml_feature_importance", "description": "Rank features by importance using Random Forest.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "target": {"type": "string"}}, "required": ["file_path", "target"]}}},
            {"type": "function", "function": {"name": "ml_auto_select", "description": "Auto-compare multiple models and pick the best one via cross-validation.", "parameters": {"type": "object", "properties": {"file_path": {"type": "string"}, "target": {"type": "string"}}, "required": ["file_path", "target"]}}},
        ]
