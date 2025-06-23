# model_utils.py

import numpy as np
from pyriemann.utils.mean import mean_riemann
from sklearn.base import BaseEstimator, TransformerMixin

class CovTransport(BaseEstimator, TransformerMixin):
    """
    Transport each covariance matrix to the global Riemann mean reference.
    Fjern person-spesifikk bias i SPD-kovarianser.
    """
    def fit(self, X, y=None):
        # X shape: (n_trials, n_channels, n_channels)
        self.G_ = mean_riemann(X)
        eigvals, eigvecs = np.linalg.eigh(self.G_)
        self.G_inv_sqrt_ = eigvecs @ np.diag(1.0/np.sqrt(eigvals)) @ eigvecs.T
        return self

    def transform(self, X):
        Gm = self.G_inv_sqrt_
        return np.array([Gm @ C @ Gm.T for C in X])
