"""Model definitions. Everything that learns from data (imputer, scaler, model) lives inside one sklearn
Pipeline, so fitting on a training fold can never touch the test fold.
"""
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def make_model(kind, params, seed):
    if kind == "logistic":
        return Pipeline([
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            ("model", LogisticRegression(C=params["C"], max_iter=params["max_iter"], random_state=seed)),
        ])
    if kind == "hgb":
        # handles missing values natively, so there's nothing to impute
        return Pipeline([("model", HistGradientBoostingClassifier(random_state=seed, **params))])
    raise ValueError(kind)


class ZoneBaseline:
    """'Is the building in a Very High zone?' turned into a probability: the destruction rate of each zone class
    in the training data. Fit on the training fold like any other model, so its Brier score is fair."""

    def __init__(self, column):
        self.column = column

    def fit(self, X, y):
        y = np.asarray(y)
        z = np.asarray(X[self.column])
        self.base_ = float(y.mean())
        self.rates_ = {v: float(y[z == v].mean()) for v in np.unique(z)}
        return self

    def predict_proba(self, X):
        p = np.array([self.rates_.get(v, self.base_) for v in np.asarray(X[self.column])])
        return np.column_stack([1 - p, p])


class ConstantBaseline:
    """Everyone gets the training destruction rate. The floor any model has to beat on Brier."""

    def fit(self, X, y):
        self.p_ = float(np.mean(y))
        return self

    def predict_proba(self, X):
        p = np.full(len(X), self.p_)
        return np.column_stack([1 - p, p])
