"""Sampling module for Wishart processes."""
import numpy as np
from scipy import linalg, stats
from sklearn.utils.extmath import fast_logdet

from regain.bayesian.stats import (log_lik_frob, log_likelihood_normal,
                                   lognormal_logpdf, lognormal_pdf, lognstat)
from regain.bayesian.wishart_process_ import GWP_construct


def elliptical_slice(
        xx, prior, cur_log_like, variance, angle_range=0, max_iter=20):
    """Markov chain update for a distribution with a Gaussian "prior" factored out.

    A Markov chain update is applied to the D-element array xx leaving a
    "posterior" distribution
        P(xx) \propto N(xx0,Sigma) \ell(xx)
    invariant. Where N(0,Sigma) is a zero-mean Gaussian distribution with
    covariance Sigma. Often \ell is a likelihood function.

    Parameters
    ----------
    xx : array-like, shape (D,)
        Initial vector.
    prior :  array-like, shape (D,)
        Single sample from N(0, Sigma)
    cur_log_like : float
        Current log-likelihood.
    angle_range : float, default 0
        Explore whole ellipse with break point at first rejection.
        Set in (0,2*pi] to explore a bracket of the specified width
        centred uniformly at random.

    Returns:
    --------
    xx : np.ndarray, shape (D,)
        Perturbed vector.
    cur_log_like : float
        Log-likelihood of xx.

    Originally written in matlab by Iain Murray
    http://homepages.inf.ed.ac.uk/imurray2/pub/10ess/elliptical_slice.m
    Iain Murray, September 2009
    Tweak to interface and documentation, September 2010

    Reference
    ---------
    Elliptical slice sampling
    Iain Murray, Ryan Prescott Adams and David J.C. MacKay.
    The Proceedings of the 13th International Conference on Artificial
    Intelligence and Statistics (AISTATS), JMLR W&CP 9:541-548, 2010.
    """
    initial_theta = xx.xx
    v, p, N = initial_theta.shape
    D = v * p * N

    S = xx.S
    L = xx.L

    cur_log_like_start = cur_log_like
    if cur_log_like is None:
        cur_log_like = log_lik_frob(S, xx.V, variance)

    # Set up the ellipse and the slice threshold
    if prior.size == D:
        #  User provided a prior sample:
        nu = prior
    else:
        #  User specified Cholesky of prior covariance:
        if prior.shape != (D, D):
            raise ValueError('Prior must be given by a D-element sample '
                             'or DxD chol(Sigma)')
        nu = np.reshape(prior.T.dot(np.random.normal(size=D)), initial_theta.shape)

    hh = 0.001 * np.log(np.random.uniform()) + cur_log_like

    #  Set up a bracket of angles and pick a first proposal.
    #  "phi = (theta'-theta)" is a change in angle.
    if angle_range <= 0:
        #  Bracket whole ellipse with both edges at first proposed point
        phi = np.random.uniform() * 2 * np.pi
        phi_min = phi - 2 * np.pi
        phi_max = phi
    else:
        #  Randomly center bracket on current point
        phi_min = -angle_range * np.random.uniform()
        phi_max = phi_min + angle_range
        phi = np.random.uniform() * (phi_max - phi_min) + phi_min

    # Slice sampling loop
    error = False
    for iteration_ in range(max_iter):
        # Compute xx for proposed angle difference and check if on the slice
        xx_proposal = np.real(initial_theta * np.cos(phi) + nu * np.sin(phi))
        uut = np.array([u.dot(u.T) for u in xx_proposal.T])
        V = GWP_construct(xx_proposal, L, uut=uut)
        cur_log_like = log_lik_frob(S, V, variance)

        if cur_log_like > hh:
            # New point is on slice, ** EXIT LOOP **
            break

        # Shrink slice to rejected point
        if phi > 0:
            phi_max = phi
        elif phi < 0:
            phi_min = phi
        else:
            # error = True
            # break
            raise RuntimeError('BUG DETECTED: Shrunk to current position '
                               'and still not acceptable.')

        # Propose new angle difference
        phi = np.random.uniform() * (phi_max - phi_min) + phi_min
    else:
        error = True

    if error:
        # revert to initial point
        xx['xx'] = initial_theta
    else:
        # update with new point
        xx['uut'] = uut
        xx['xx'] = xx_proposal
        xx['V'] = V

    # return xx, cur_log_like_start if error else cur_log_like
    return xx, cur_log_like_start if error else cur_log_like


def sample_hyper_kernel(
        initial_theta, var_proposal, t, u, kern, mean_prior, var_prior):
    """Metropolis-Hastings for sampling the posterior of the kernel
    hyperparameter.

    According to the paper, we use a lognormal distribution as the proposal.

    Parameters
    ----------
    initial_theta : type
        Description of parameter `initial_theta`.
    var_proposal : type
        Description of parameter `var_proposal`.
    t : type
        Description of parameter `t`.
    u : type
        Description of parameter `u`.
    kern : type
        Description of parameter `kern`.
    mean_prior : type
        Description of parameter `mean_prior`.
    var_prior : type
        Description of parameter `var_prior`.

    Returns
    -------
    type
        Description of returned object.

    """
    # Propose a sample
    mu, sigma = lognstat(initial_theta, var_proposal)
    proposal = np.random.lognormal(mu, sigma)

    # Criterion to choose whether to accept the proposed sample or not
    logpzast = logpunorm(proposal, t, u, kern, mean_prior, var_prior)
    qzastztau = lognormal_pdf(proposal, mu=mu, sigma=sigma)

    mu, sigma = lognstat(proposal, var_proposal)
    logpztau = logpunorm(initial_theta, t, u, kern, mean_prior, var_prior)
    qztauzast = lognormal_pdf(initial_theta, mu=mu, sigma=sigma)

    acceptance_proba = min(
        1, np.exp(logpzast - logpztau) * (qztauzast / qzastztau))

    # Now we decide whether to accept zast or use the previous value
    accept = np.random.uniform() < acceptance_proba
    sample = proposal if accept else initial_theta
    return sample, accept


def logpunorm(inverse_width, t, umat, kern, mean_prior, var_prior):
    """Posterior probability of inverse_width.

    Parameters
    ----------
    inverse_width : float
        Kernel parameter.
    t : ndarray
        Points where to compute the kernel.
    umat : ndarray, shape (v, p, n)
        Sample tensor.
    kern : function
        Function for computing the kernel.
    mean_prior : float
        Prior for the mean.
    var_prior : float
        Prior for the variance.

    Returns
    -------
    logprob
        Posterior probability.
    """
    K = kern(t[:, None], inverse_width=inverse_width)
    k_inverse = linalg.pinvh(K)

    v, p, n = umat.shape
    F = np.tensordot(umat, umat, axes=([1, 0], [1, 0]))

    logpugl = v * p * fast_logdet(K) + np.sum(F * k_inverse)
    logpugl += umat.size * np.log(2 * np.pi)
    logpugl *= -0.5

    mu_prior, sigma_prior = lognstat(mean_prior, var_prior)
    logp_prior = lognormal_logpdf(inverse_width, mu=mu_prior, sigma=sigma_prior)

    logprob = logpugl + logp_prior
    return logprob


def sample_L2(Ltau, var_proposal, S, umat, var_err,
              mu_prior, var_prior, uut=None):
    """Metropolis-Hastings for sampling the posterior of the elements in L.

    Use a spherical normal distribution as the proposal.
    """
    # Run the MH individually per component of L
    free_elements = Ltau.size
    L_proposal = np.zeros(free_elements)
    for i in range(free_elements):
        L_proposal[i] = _sample_ell_comp(
            Ltau, i, var_proposal[i], S, umat, var_err,
            mu_prior=mu_prior[i], var_prior=var_prior[i], uut=uut)
        Ltau[i] = L_proposal[i]

    return L_proposal


def _sample_ell_comp(
        Ltaug, i, sigma2Lprop, S, umat, var_err,
        mu_prior, var_prior, uut=None):
    """Sample a single element for L."""
    # Propose a sample
    Ltau = Ltaug[i]
    Last = np.random.normal(Ltau, np.sqrt(sigma2Lprop))
    Lastg = Ltaug.copy()
    Lastg[i] = Last

    # Criterion to choose whether to accept the proposed sample or not
    # normpdf = lambda x, m, s: np.exp(-0.5 * ((x - m)/s)**2) / (np.sqrt(2*np.pi) * s)

    logpLast = logp_ell_posterior(Lastg, i, S, umat, var_err, mu_prior, var_prior, uut=uut)
    q_ast_tau = stats.norm.pdf(Last, Ltau, np.sqrt(sigma2Lprop))

    logpLtau = logp_ell_posterior(Ltaug, i, S, umat, var_err, mu_prior, var_prior, uut=uut)
    q_tau_ast = stats.norm.pdf(Ltau, Last, np.sqrt(sigma2Lprop))

    A = min(1, np.exp(logpLast - logpLtau) * (q_tau_ast / q_ast_tau))

    # Now we decide whether to accept zast or use the previous value
    return Last if np.random.uniform() < A else Ltau


def logp_ell_posterior(Lv, i, S, umat, var_err, mu_prior, var_prior, uut=None):
    L = np.zeros_like(S[..., 0])  # p times p
    L[np.tril_indices_from(L)] = Lv
    D = GWP_construct(umat, L, uut=uut)
    logpS = log_lik_frob(S, D, var_err)
    logpL = log_likelihood_normal(Lv[i], mu_prior, var_prior)
    return logpS + logpL
