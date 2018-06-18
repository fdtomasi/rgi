"""Test LatentGraphLasso."""
import numpy as np
import warnings

from numpy.testing import assert_array_equal

from regain.covariance.latent_graph_lasso_ import LatentGraphLasso


def test_lgl_zero():
    """Check that LatentGraphLasso can handle zero data."""
    a = np.zeros((3, 3))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mdl = LatentGraphLasso(max_iter=1, assume_centered=True).fit(a)

    mdl.precision_.flat[::4] = 0

    assert_array_equal(mdl.precision_, a)
    assert_array_equal(mdl.latent_, a)
    assert_array_equal(mdl.get_precision(),
                       mdl.precision_ - mdl.latent_)
