import os
import sys
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import rcParams
try:
    from mc3.stats import time_avg
except ModuleNotFoundError:
    print("Could not import MC3. No RMS time-averaging plots will be made.")
import corner
from scipy import stats
import fleck
import astropy.units as unit
try:
    import arviz as az
    from arviz.rcparams import rcParams as az_rcParams
    import starry
except ModuleNotFoundError:
    # PyMC3 hasn't been installed
    pass
import warnings
warnings.filterwarnings("ignore", message='Ignoring specified arguments in '
                                          'this call because figure with num')

from ..lib import plots, util
from ..lib.split_channels import split
from .models.AstroModel import PlanetParams


def plot_fit(lc, model, meta, fitter, isTitle=True):
    """Plot the fitted model over the data. (Figs 5101)

    Parameters
    ----------
    lc : eureka.S5_lightcurve_fitting.lightcurve.LightCurve
        The lightcurve data object.
    model : eureka.S5_lightcurve_fitting.models.CompositeModel
        The fitted composite model.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    fitter : str
        The name of the fitter (for plot filename).
    isTitle : bool; optional
        Should figure have a title. Defaults to True.
    """
    if not isinstance(fitter, str):
        raise ValueError(f'Expected type str for fitter, instead received a '
                         f'{type(fitter)}')

    model_sys_full = model.syseval()
    model_phys_full, new_time, nints_interp = \
        model.physeval(interp=meta.interp)
    model_noGP = model.eval(incl_GP=False)
    model_gp = model.GPeval(model_noGP)
    model_eval = model_noGP+model_gp

    for i, channel in enumerate(lc.fitted_channels):
        flux = np.ma.copy(lc.flux)
        unc = np.ma.copy(lc.unc_fit)
        model_lc = np.ma.copy(model_eval)
        gp = np.ma.copy(model_gp)
        model_sys = model_sys_full
        model_phys = model_phys_full
        color = lc.colors[i]

        if lc.share and not meta.multwhite:
            time = lc.time
            new_timet = new_time

            # Split the arrays that have lengths of the original time axis
            flux, unc, model_lc, model_sys, gp = \
                split([flux, unc, model_lc, model_sys, gp],
                      meta.nints, channel)

            # Split the arrays that have lengths of the new (potentially
            # interpolated) time axis
            model_phys = split([model_phys, ], nints_interp, channel)[0]
        elif meta.multwhite:
            # Split the arrays that have lengths of the original time axis
            time, flux, unc, model_lc, model_sys, gp = \
                split([lc.time, flux, unc, model_lc, model_sys, gp],
                      meta.nints, channel)

            # Split the arrays that have lengths of the new (potentially
            # interpolated) time axis
            model_phys, new_timet = split([model_phys, new_time],
                                          nints_interp, channel)
        else:
            time = lc.time
            new_timet = new_time

        residuals = flux - model_lc

        # Get binned data and times
        if not meta.nbin_plot or meta.nbin_plot > len(time):
            binned_time = time
            binned_flux = flux
            binned_unc = unc
            binned_normflux = flux/model_sys - gp
            binned_res = residuals
        else:
            nbin_plot = meta.nbin_plot
            binned_time = util.binData_time(time, time, nbin=nbin_plot)
            binned_flux = util.binData_time(flux, time, nbin=nbin_plot)
            binned_unc = util.binData_time(unc, time, nbin=nbin_plot, err=True)
            binned_normflux = util.binData_time(flux/model_sys - gp, time,
                                                nbin=nbin_plot)
            binned_res = util.binData_time(residuals, time, nbin=nbin_plot)

        fig = plt.figure(5101, figsize=(8, 6))
        plt.clf()

        ax = fig.subplots(3, 1)
        ax[0].errorbar(binned_time, binned_flux, yerr=binned_unc, fmt='.',
                       color='w', ecolor=color, mec=color)
        ax[0].plot(time, model_lc, '.', ls='', ms=1, color='0.3', zorder=10)
        if isTitle:
            ax[0].set_title(f'{meta.eventlabel} - Channel {channel} - '
                            f'{fitter}')
        ax[0].set_ylabel('Normalized Flux', size=14)
        ax[0].set_xticks([])

        ax[1].errorbar(binned_time, binned_normflux, yerr=binned_unc, fmt='.',
                       color='w', ecolor=color, mec=color)
        ax[1].plot(new_timet, model_phys, color='0.3', zorder=10)
        ax[1].set_ylabel('Calibrated Flux', size=14)
        ax[1].set_xticks([])

        ax[2].errorbar(binned_time, binned_res*1e6, yerr=binned_unc*1e6,
                       fmt='.', color='w', ecolor=color, mec=color)
        ax[2].axhline(0, color='0.3', zorder=10)
        ax[2].set_ylabel('Residuals (ppm)', size=14)
        ax[2].set_xlabel(str(lc.time_units), size=14)

        fig.get_layout_engine().set(hspace=0, h_pad=0)
        fig.align_ylabels(ax)

        if lc.white:
            fname_tag = 'white'
        else:
            ch_number = str(channel).zfill(len(str(lc.nchannel)))
            fname_tag = f'ch{ch_number}'
        fname = (f'figs{os.sep}fig5101_{fname_tag}_lc_{fitter}'
                 + plots.figure_filetype)
        fig.savefig(meta.outputdir+fname, bbox_inches='tight', dpi=300)
        if not meta.hide_plots:
            plt.pause(0.2)


def plot_phase_variations(lc, model, meta, fitter, isTitle=True):
    """Plot the fitted model over the data. (Figs 5104 and Figs 5304)

    Parameters
    ----------
    lc : eureka.S5_lightcurve_fitting.lightcurve.LightCurve
        The lightcurve data object.
    model : eureka.S5_lightcurve_fitting.models.CompositeModel
        The fitted composite model.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    fitter : str
        The name of the fitter (for plot filename).
    isTitle : bool; optional
        Should figure have a title. Defaults to True.
    """
    if not isinstance(fitter, str):
        raise ValueError(f'Expected type str for fitter, instead received a '
                         f'{type(fitter)}')

    model_sys = model.syseval()
    model_noGP = model.eval(incl_GP=False)
    model_gp = model.GPeval(model_noGP)
    model_phys_full, new_time, nints_interp = \
        model.physeval(interp=meta.interp)

    flux_full = np.ma.copy(lc.flux)
    unc_full = np.ma.copy(lc.unc_fit)
    flux_full = flux_full/model_sys-model_gp

    # Normalize to zero flux at eclipse
    flux_full -= 1
    model_phys_full -= 1

    # Convert to ppm
    model_phys_full *= 1e6
    flux_full *= 1e6
    unc_full *= 1e6

    for i, channel in enumerate(lc.fitted_channels):
        flux = np.ma.copy(flux_full)
        unc = np.ma.copy(unc_full)
        model_phys = np.ma.copy(model_phys_full)
        color = lc.colors[i]

        if lc.share and not meta.multwhite:
            time = lc.time
            new_timet = new_time

            # Split the arrays that have lengths of the original time axis
            flux, unc = split([flux, unc], meta.nints, channel)

            # Split the arrays that have lengths of the new (potentially
            # interpolated) time axis
            model_phys = split([model_phys, ],
                               nints_interp, channel)[0]
        elif meta.multwhite:
            # Split the arrays that have lengths of the original time axis
            time, flux, unc = split([lc.time, flux, unc],
                                    meta.nints, channel)

            # Split the arrays that have lengths of the new (potentially
            # interpolated) time axis
            model_phys, new_timet = split([model_phys, new_time],
                                          nints_interp, channel)
        else:
            time = lc.time
            new_timet = new_time

        # Get binned data and times
        if not meta.nbin_plot or meta.nbin_plot > len(time):
            binned_time = time
            binned_flux = flux
            binned_unc = unc
        else:
            nbin_plot = meta.nbin_plot
            binned_time = util.binData_time(time, time, nbin=nbin_plot)
            binned_flux = util.binData_time(flux, time, nbin=nbin_plot)
            binned_unc = util.binData_time(unc, time, nbin=nbin_plot, err=True)

        # Setup the figure
        fig = plt.figure(5104, figsize=(8, 6))
        plt.clf()
        ax = fig.gca()
        if isTitle:
            ax.set_title(f'{meta.eventlabel} - Channel {channel} - '
                         f'{fitter}')
        ax.set_ylabel('Normalized Flux - 1 (ppm)', size=14)
        ax.set_xlabel(str(lc.time_units), size=14)
        fig.patch.set_facecolor('white')

        # Plot the binned observations
        ax.errorbar(binned_time, binned_flux, yerr=binned_unc, fmt='.',
                    color='w', ecolor=color, mec=color)
        # Plot the model
        ax.plot(new_timet, model_phys, '.', ls='', ms=2, color='0.3',
                zorder=10)

        # Set nice axis limits
        sigma = np.ma.mean(binned_unc)
        max_astro = np.ma.max((model_phys-1))
        ax.set_ylim(-6*sigma, max_astro+6*sigma)
        ax.set_xlim(np.ma.min(time), np.ma.max(time))

        # Save/show the figure
        if lc.white:
            fname_tag = 'white'
        else:
            ch_number = str(channel).zfill(len(str(lc.nchannel)))
            fname_tag = f'ch{ch_number}'
        fname = (f'figs{os.sep}fig5104_{fname_tag}_phaseVariations_{fitter}'
                 + plots.figure_filetype)
        fig.savefig(meta.outputdir+fname, bbox_inches='tight', dpi=300)
        if not meta.hide_plots:
            plt.pause(0.2)

        if meta.isplots_S5 >= 3:
            # Setup the figure
            fig = plt.figure(5304, figsize=(8, 6))
            plt.clf()
            ax = fig.gca()
            if isTitle:
                ax.set_title(f'{meta.eventlabel} - Channel {channel} - '
                             f'{fitter}')
            ax.set_ylabel('Normalized Flux - 1 (ppm)', size=14)
            ax.set_xlabel(str(lc.time_units), size=14)
            fig.patch.set_facecolor('white')

            # Plot the unbinned data without errorbars
            ax.plot(time, flux, '.', c='k', zorder=0, alpha=0.01)
            # Plot the binned data with errorbars
            ax.errorbar(binned_time, binned_flux, yerr=binned_unc, fmt='.',
                        color=color, zorder=1)
            # Plot the physical model
            ax.plot(new_timet, model_phys, '.', ls='', ms=2, color='0.3',
                    zorder=10)

            # Set nice axis limits
            ax.set_ylim(-3*sigma, max_astro+3*sigma)
            ax.set_xlim(np.ma.min(time), np.ma.max(time))
            # Save/show the figure
            if lc.white:
                fname_tag = 'white'
            else:
                ch_number = str(channel).zfill(len(str(lc.nchannel)))
                fname_tag = f'ch{ch_number}'
            fname = (f'figs{os.sep}fig5304_{fname_tag}_phaseVariations'
                     f'_{fitter}' + plots.figure_filetype)
            fig.savefig(meta.outputdir+fname, bbox_inches='tight', dpi=300)
            if not meta.hide_plots:
                plt.pause(0.2)


def plot_rms(lc, model, meta, fitter):
    """Create a RMS time-averaging plot to look for red noise. (Figs 5301)

    Parameters
    ----------
    lc : eureka.S5_lightcurve_fitting.lightcurve.LightCurve
        The lightcurve data object.
    model : eureka.S5_lightcurve_fitting.models.CompositeModel
        The fitted composite model.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    fitter : str
        The name of the fitter (for plot filename).
    """
    if not isinstance(fitter, str):
        raise ValueError(f'Expected type str for fitter, instead received a '
                         f'{type(fitter)}')

    model_eval = model.eval(incl_GP=True)

    for channel in lc.fitted_channels:
        if 'mc3.stats' not in sys.modules:
            # If MC3 failed to load, exit for loop
            break
        flux = np.ma.copy(lc.flux)
        model_lc = np.ma.copy(model_eval)

        if lc.share and not meta.multwhite:
            time = lc.time

            # Split the arrays that have lengths of the original time axis
            flux, model_lc = split([flux, model_lc], meta.nints, channel)
        elif meta.multwhite:
            # Split the arrays that have lengths of the original time axis
            time, flux, model_lc = split([lc.time, flux, model_lc],
                                         meta.nints, channel)
        else:
            time = lc.time

        residuals = np.ma.masked_invalid(flux-model_lc)
        residuals = residuals[np.ma.argsort(time)]

        # Remove masked values
        residuals = residuals[~np.ma.getmaskarray(residuals)]
        # Compute RMS range
        maxbins = residuals.size//10
        if maxbins < 2:
            maxbins = residuals.size//2
        rms, rmslo, rmshi, stderr, binsz = time_avg(residuals,
                                                    maxbins=maxbins,
                                                    binstep=1)
        normfactor = 1e-6
        fig = plt.figure(
            int('52{}'.format(str(0).zfill(len(str(lc.nchannel))))),
            figsize=(8, 6))
        fig.clf()
        ax = fig.gca()
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.set_title(' Correlated Noise', size=16, pad=20)
        # our noise
        ax.plot(binsz, rms/normfactor, color='black', lw=1.5,
                label='Fit RMS', zorder=4)
        ax.fill_between(binsz, (rms-rmslo)/normfactor, (rms+rmshi)/normfactor,
                        facecolor='k', alpha=0.3, label='Fit RMS Uncertainty',
                        zorder=3)
        # expected noise
        ax.plot(binsz, stderr/normfactor, color='red', ls='-', lw=2,
                label='Gaussian Std. Err.', zorder=1)

        # Format the main axes
        ax.set_xlabel("Bin Size (N frames)", fontsize=14)
        ax.set_ylabel("RMS (ppm)", fontsize=14)
        ax.tick_params(axis='both', labelsize=12)
        ax.legend(loc=1)

        # Add second x-axis using time instead of N-binned
        dt = np.ma.min(np.ma.diff(time))*24*3600

        def t_N(N):
            return N*dt

        def N_t(t):
            return t/dt

        ax2 = ax.secondary_xaxis('top', functions=(t_N, N_t))
        ax2.set_xlabel('Bin Size (seconds)', fontsize=14)
        ax2.tick_params(axis='both', labelsize=12)

        if lc.white:
            fname_tag = 'white'
        else:
            ch_number = str(channel).zfill(len(str(lc.nchannel)))
            fname_tag = f'ch{ch_number}'
        fname = (f'figs{os.sep}fig5301_{fname_tag}_RMS_TimeAveraging_{fitter}'
                 + plots.figure_filetype)
        plt.savefig(meta.outputdir+fname, bbox_inches='tight', dpi=300)
        if not meta.hide_plots:
            plt.pause(0.2)


def plot_corner(samples, lc, meta, freenames, fitter):
    """Plot a corner plot. (Figs 5501)

    Parameters
    ----------
    samples : ndarray
        The samples produced by the sampling algorithm.
    lc : eureka.S5_lightcurve_fitting.lightcurve.LightCurve
        The lightcurve data object.
    freenames : iterable
        The names of the fitted parameters.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    fitter : str
        The name of the fitter (for plot filename).
    """
    ndim = len(freenames)+1  # One extra for the 1D histogram

    # Don't allow offsets or scientific notation in tick labels
    old_useOffset = rcParams['axes.formatter.useoffset']
    old_xtick_labelsize = rcParams['xtick.labelsize']
    old_ytick_labelsize = rcParams['ytick.labelsize']
    old_constrained_layout = rcParams['figure.constrained_layout.use']
    rcParams['axes.formatter.useoffset'] = False
    rcParams['xtick.labelsize'] = 10
    rcParams['ytick.labelsize'] = 10
    rcParams['figure.constrained_layout.use'] = False

    fig = plt.figure(5501, figsize=(ndim*1.4, ndim*1.4))
    fig.clf()
    fig = corner.corner(samples, fig=fig, quantiles=[0.16, 0.5, 0.84],
                        max_n_ticks=3, labels=freenames, show_titles=True,
                        title_fmt='.3', title_kwargs={"fontsize": 10},
                        label_kwargs={"fontsize": 10}, fontsize=10,
                        labelpad=0.25)

    if lc.white:
        fname_tag = 'white'
    else:
        ch_number = str(lc.channel).zfill(len(str(lc.nchannel)))
        fname_tag = f'ch{ch_number}'
    fname = (f'figs{os.sep}fig5501_{fname_tag}_corner_{fitter}'
             + plots.figure_filetype)
    fig.savefig(meta.outputdir+fname, bbox_inches='tight', pad_inches=0.05,
                dpi=300)
    if not meta.hide_plots:
        plt.pause(0.2)

    rcParams['axes.formatter.useoffset'] = old_useOffset
    rcParams['xtick.labelsize'] = old_xtick_labelsize
    rcParams['ytick.labelsize'] = old_ytick_labelsize
    rcParams['figure.constrained_layout.use'] = old_constrained_layout


def plot_chain(samples, lc, meta, freenames, fitter='emcee', burnin=False,
               nburn=0, nrows=3, ncols=4, nthin=1):
    """Plot the evolution of the chain to look for temporal trends. (Figs 5303)

    Parameters
    ----------
    samples : ndarray
        The samples produced by the sampling algorithm.
    lc : eureka.S5_lightcurve_fitting.lightcurve.LightCurve
        The lightcurve data object.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    freenames : iterable
        The names of the fitted parameters.
    fitter : str; optional
        The name of the fitter (for plot filename). Defaults to 'emcee'.
    burnin : bool; optional
        Whether or not the samples include the burnin phase. Defaults to False.
    nburn : int; optional
        The number of burn-in steps that are discarded later. Defaults to 0.
    nrows : int; optional
        The number of rows to make per figure. Defaults to 3.
    ncols : int; optional
        The number of columns to make per figure. Defaults to 4.
    nthin : int; optional
        If >1, the plot will use every nthin point to help speed up
        computation and reduce clutter on the plot. Defaults to 1.
    """
    nsubplots = nrows*ncols
    nplots = int(np.ceil(len(freenames)/nsubplots))

    k = 0
    for plot_number in range(nplots):
        fig = plt.figure(5303, figsize=(6*ncols, 4*nrows))
        fig.clf()
        axes = fig.subplots(nrows, ncols, sharex=True)

        for j in range(ncols):
            for i in range(nrows):
                if k >= samples.shape[2]:
                    axes[i][j].set_axis_off()
                    continue
                vals = samples[::nthin, :, k]
                xvals = np.arange(samples.shape[0])[::nthin]
                n3sig, n2sig, n1sig, med, p1sig, p2sig, p3sig = \
                    np.percentile(vals, [0.15, 2.5, 16, 50, 84, 97.5, 99.85],
                                  axis=1)
                axes[i][j].fill_between(xvals, n3sig, p3sig, alpha=0.2,
                                        label=r'3$\sigma$')
                axes[i][j].fill_between(xvals, n2sig, p2sig, alpha=0.2,
                                        label=r'2$\sigma$')
                axes[i][j].fill_between(xvals, n1sig, p1sig, alpha=0.2,
                                        label=r'1$\sigma$')
                axes[i][j].plot(xvals, med, label='Median')
                axes[i][j].set_ylabel(freenames[k])
                axes[i][j].set_xlim(0, samples.shape[0]-1)
                for arr in [n3sig, n2sig, n1sig, med, p1sig, p2sig, p3sig]:
                    # Add some horizontal lines to make movement in walker
                    # population more obvious
                    axes[i][j].axhline(arr[0], ls='dotted', c='k', lw=1)
                if burnin and nburn > 0:
                    axes[i][j].axvline(nburn, ls='--', c='k',
                                       label='End of Burn-In')
                add_legend = ((j == (ncols-1) and i == (nrows//2)) or
                              (k == samples.shape[2]-1))
                if add_legend:
                    axes[i][j].legend(loc=6, bbox_to_anchor=(1.01, 0.5))
                k += 1
        fig.get_layout_engine().set(h_pad=0)

        if lc.white:
            fname_tag = 'white'
        else:
            ch_number = str(lc.channel).zfill(len(str(lc.nchannel)))
            fname_tag = f'ch{ch_number}'
        fname = f'figs{os.sep}fig5303_{fname_tag}'
        if burnin:
            fname += '_burninchain'
        else:
            fname += '_chain'
        fname += '_'+fitter
        if nplots > 1:
            fname += f'_plot{plot_number+1}of{nplots}'
        fname += plots.figure_filetype
        fig.savefig(meta.outputdir+fname, bbox_inches='tight',
                    pad_inches=0.05, dpi=300)
        if not meta.hide_plots:
            plt.pause(0.2)


def plot_trace(trace, model, lc, freenames, meta, fitter='nuts', compact=False,
               **kwargs):
    """Plot the evolution of the trace to look for temporal trends. (Figs 5305)

    Parameters
    ----------
    trace : pymc3.backends.base.MultiTrace or arviz.InferenceData
        A ``MultiTrace`` or ArviZ ``InferenceData`` object that contains the
        samples.
    model :

    lc : eureka.S5_lightcurve_fitting.lightcurve.LightCurve
        The lightcurve data object.
    freenames : iterable
        The names of the fitted parameters.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    fitter : str; optional
        The name of the fitter (for plot filename). Defaults to 'nuts'.
    compact: bool; optional
        Plot multidimensional variables in a single plot. Defailts to False.
    **kwargs : dict
        Additional keyword arguments to pass to pm.traceplot.
    """

    max_subplots = az_rcParams['plot.max_subplots'] // 2
    nplots = int(np.ceil(len(freenames)/max_subplots))
    npanels = min([len(freenames), max_subplots])

    for i in range(nplots):
        with model.model:
            ax = az.plot_trace(trace,
                               var_names=freenames[i*npanels:(i+1)*npanels],
                               compact=compact, show=False, **kwargs)
        fig = ax[0][0].figure

        if lc.white:
            fname_tag = 'white'
        else:
            ch_number = str(lc.channel).zfill(len(str(lc.nchannel)))
            fname_tag = f'ch{ch_number}'
        fname = f'figs{os.sep}fig5305_{fname_tag}_trace'
        fname += '_'+fitter
        fname += f'figure{i+1}of{nplots}'
        fname += plots.figure_filetype
        fig.savefig(meta.outputdir+fname, bbox_inches='tight',
                    pad_inches=0.05, dpi=300)
        if not meta.hide_plots:
            plt.pause(0.2)
        else:
            plt.close(fig)


def plot_res_distr(lc, model, meta, fitter):
    """Plot the normalized distribution of residuals + a Gaussian. (Fig 5302)

    Parameters
    ----------
    lc : eureka.S5_lightcurve_fitting.lightcurve.LightCurve
        The lightcurve data object.
    model : eureka.S5_lightcurve_fitting.models.CompositeModel
        The fitted composite model.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    fitter : str
        The name of the fitter (for plot filename).
    """
    if not isinstance(fitter, str):
        raise ValueError(f'Expected type str for fitter, instead received a '
                         f'{type(fitter)}')

    model_eval = model.eval(incl_GP=True)

    for channel in lc.fitted_channels:
        plt.figure(5302, figsize=(8, 6))
        plt.clf()

        flux = np.ma.copy(lc.flux)
        unc = np.ma.copy(lc.unc_fit)
        model_lc = np.ma.copy(model_eval)

        if lc.share or meta.multwhite:
            # Split the arrays that have lengths of the original time axis
            flux, unc, model_lc = split([flux, unc, model_lc],
                                        meta.nints, channel)

        residuals = flux - model_lc
        hist_vals = residuals/unc
        # Mask out any infinities or nans
        hist_vals = np.ma.masked_invalid(hist_vals)

        n, bins, patches = plt.hist(hist_vals, alpha=0.5, color='b',
                                    edgecolor='b', lw=1)
        x = np.linspace(-4., 4., 200)
        px = stats.norm.pdf(x, loc=0, scale=1)
        plt.plot(x, px*(bins[1]-bins[0])*len(residuals), 'k-', lw=2)
        plt.xlabel("Residuals/Uncertainty", fontsize=14)
        if lc.white:
            fname_tag = 'white'
        else:
            ch_number = str(channel).zfill(len(str(lc.nchannel)))
            fname_tag = f'ch{ch_number}'
        fname = (f'figs{os.sep}fig5302_{fname_tag}_res_distri_{fitter}'
                 + plots.figure_filetype)
        plt.savefig(meta.outputdir+fname, bbox_inches='tight', dpi=300)
        if not meta.hide_plots:
            plt.pause(0.2)


def plot_GP_components(lc, model, meta, fitter, isTitle=True):
    """Plot the lightcurve + GP model + residuals (Figs 5102)

    Parameters
    ----------
    lc : eureka.S5_lightcurve_fitting.lightcurve.LightCurve
        The lightcurve data object.
    model : eureka.S5_lightcurve_fitting.models.CompositeModel
        The fitted composite model.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    fitter : str
        The name of the fitter (for plot filename).
    isTitle : bool; optional
        Should figure have a title. Defaults to True.
    """
    if not isinstance(fitter, str):
        raise ValueError(f'Expected type str for fitter, instead received a '
                         f'{type(fitter)}')

    model_eval = model.eval()
    model_GP = model.GPeval(model_eval)
    model_with_GP = model_eval + model_GP

    for i, channel in enumerate(lc.fitted_channels):
        flux = np.ma.copy(lc.flux)
        unc = np.ma.copy(lc.unc_fit)
        model_lc = np.ma.copy(model_with_GP)
        model_GP_component = np.ma.copy(model_GP)
        color = lc.colors[i]

        if lc.share and not meta.multwhite:
            time = lc.time
            # Split the arrays that have lengths of the original time axis
            flux, unc, model_lc, model_GP_component = \
                split([flux, unc, model_lc, model_GP_component],
                      meta.nints, channel)
        elif meta.multwhite:
            # Split the arrays that have lengths of the original time axis
            time, flux, unc, model_lc, model_GP_component = \
                split([lc.time, flux, unc, model_lc, model_GP_component],
                      meta.nints, channel)
        else:
            time = lc.time

        residuals = flux - model_lc
        fig = plt.figure(5102, figsize=(8, 6))
        plt.clf()
        ax = fig.subplots(3, 1)
        ax[0].errorbar(time, flux, yerr=unc, fmt='.', color='w',
                       ecolor=color, mec=color)
        ax[0].plot(time, model_lc, '.', ls='', ms=2, color='0.3',
                   zorder=10)
        if isTitle:
            ax[0].set_title(f'{meta.eventlabel} - Channel {channel} - '
                            f'{fitter}')
        ax[0].set_ylabel('Normalized Flux', size=14)
        ax[0].set_xticks([])

        ax[1].plot(time, model_GP_component*1e6, '.', color=color)
        ax[1].set_ylabel('GP Term (ppm)', size=14)
        ax[1].set_xticks([])

        ax[2].errorbar(time, residuals*1e6, yerr=unc*1e6, fmt='.',
                       color='w', ecolor=color, mec=color)
        ax[2].axhline(0, color='0.3', zorder=10)
        ax[2].set_ylabel('Residuals (ppm)', size=14)
        ax[2].set_xlabel(str(lc.time_units), size=14)

        fig.get_layout_engine().set(hspace=0, h_pad=0)
        fig.align_ylabels(ax)

        if lc.white:
            fname_tag = 'white'
        else:
            ch_number = str(channel).zfill(len(str(lc.nchannel)))
            fname_tag = f'ch{ch_number}'
        fname = (f'figs{os.sep}fig5102_{fname_tag}_lc_GP_{fitter}'
                 + plots.figure_filetype)
        fig.savefig(meta.outputdir+fname, bbox_inches='tight', dpi=300)
        if not meta.hide_plots:
            plt.pause(0.2)


def plot_eclipse_map(lc, flux_maps, meta, fitter):
    """Plot fitted eclipse map and lat-lon slices (Figs 5105)

    Parameters
    ----------
    lc : eureka.S5_lightcurve_fitting.lightcurve.LightCurve
        The lightcurve data object.
    flux_maps : array
        The posterior distribution of the fitted maps
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    fitter : str
        The name of the fitter (for plot filename).
    """
    for i, channel in enumerate(lc.fitted_channels):
        fig = plt.figure(5105, figsize=(12, 3))
        fig.clf()
        axs = fig.subplots(1, 3, width_ratios=[1.4, 1, 1])

        lons = np.linspace(-180, 180, np.shape(flux_maps)[2])
        lats = np.linspace(-90, 90, np.shape(flux_maps)[1])

        # Quantiles
        p1 = 0.841
        p2 = 0.977
        p3 = 0.998

        # Plot median map
        ca = axs[0].contourf(lons, lats,
                             np.quantile(1e6*flux_maps[:], 0.5, axis=0),
                             cmap='RdBu_r')
        axs[0].axhline(0, color='C0', ls='--')
        axs[0].axvline(0, color='C3', ls='--')
        axs[0].set_xticks([-180, -90, 0, 90, 180])
        axs[0].set_yticks([-90, -45, 0, 45, 90])
        axs[0].set_xlim([-180, 180])
        axs[0].set_ylim([-90, 90])
        fig.colorbar(ca, ax=axs[0], pad=-0.04,
                     label=r'$F_{\rm p}/F_{\rm s}$ (ppm)')

        # Plot slice along equator
        lat0 = int(np.shape(flux_maps)[2]/2)
        axs[1].fill_between(lons,
                            1e6*np.quantile(flux_maps[:, lat0], p1, axis=0),
                            1e6*np.quantile(flux_maps[:, lat0], 1-p1, axis=0),
                            color='C0', alpha=0.3, ls='None')
        axs[1].fill_between(lons,
                            1e6*np.quantile(flux_maps[:, lat0], p2, axis=0),
                            1e6*np.quantile(flux_maps[:, lat0], 1-p2, axis=0),
                            color='C0', alpha=0.3, ls='None')
        axs[1].fill_between(lons,
                            1e6*np.quantile(flux_maps[:, lat0], p3, axis=0),
                            1e6*np.quantile(flux_maps[:, lat0], 1-p3, axis=0),
                            color='C0', alpha=0.3, ls='None')
        axs[1].set_xlim([-180, 180])
        axs[1].set_xticks([-180, -90, 0, 90, 180])

        # Plot slice along equator
        lon0 = int(np.shape(flux_maps)[1]/2)
        axs[2].fill_between(
            lats,
            1e6*np.quantile(flux_maps[:, :, lon0], p1, axis=0),
            1e6*np.quantile(flux_maps[:, :, lon0], 1-p1, axis=0),
            color='C3', alpha=0.3, ls='None')
        axs[2].fill_between(
            lats,
            1e6*np.quantile(flux_maps[:, :, lon0], p2, axis=0),
            1e6*np.quantile(flux_maps[:, :, lon0], 1-p2, axis=0),
            color='C3', alpha=0.3, ls='None')
        axs[2].fill_between(
            lats,
            1e6*np.quantile(flux_maps[:, :, lon0], p3, axis=0),
            1e6*np.quantile(flux_maps[:, :, lon0], 1-p3, axis=0),
            color='C3', alpha=0.3, ls='None')
        axs[2].set_xlim([-90, 90])
        axs[2].set_xticks([-90, -45, 0, 45, 90])

        axs[0].set_title('Median Map')
        axs[1].set_title('Flux Along Equator')
        axs[2].set_title(r'Flux Along 0$^{\circ}$ Longitude')
        axs[0].set_ylabel('Latitude', labelpad=-10)
        axs[0].set_xlabel('Longitude')
        axs[1].set_xlabel('Longitude')
        axs[2].set_xlabel('Latitude')
        axs[1].set_ylabel(r'$F_{\rm p}/F_{\rm s}$ (ppm)')
        axs[2].set_ylabel(r'$F_{\rm p}/F_{\rm s}$ (ppm)')

        fig.get_layout_engine().set(wspace=0.05, w_pad=0)

        if lc.white:
            fname_tag = 'white'
        else:
            ch_number = str(channel).zfill(len(str(lc.nchannel)))
            fname_tag = f'ch{ch_number}'
        fname = (f'figs{os.sep}fig5105_{fname_tag}_eclipseMap_{fitter}' +
                 plots.figure_filetype)

        fig.savefig(meta.outputdir+fname, bbox_inches='tight', dpi=300)
        if not meta.hide_plots:
            plt.pause(0.2)


def plot_fleck_star(lc, model, meta, fitter):
    """Plot the location and contrast of the fleck star spots (Figs 5307)

    Parameters
    ----------
    lc : eureka.S5_lightcurve_fitting.lightcurve.LightCurve
        The lightcurve data object.
    model : eureka.S5_lightcurve_fitting.models.CompositeModel
        The fitted composite model.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    fitter : str
        The name of the fitter (for plot filename).
    """
    for c in range(lc.nchannel_fitted):
        channel = lc.fitted_channels[c]
        if lc.nchannel_fitted > 1:
            chan = channel
        else:
            chan = 0

        # Initialize PlanetParams object
        pl_params = PlanetParams(model, 0, chan)

        # create arrays to hold values
        spotrad = np.zeros(0)
        spotlat = np.zeros(0)
        spotlon = np.zeros(0)

        for n in range(pl_params.nspots):
            # read radii, latitudes, longitudes, and contrasts
            if n > 0:
                spot_id = f'{n}'
            else:
                spot_id = ''
            spotrad = np.concatenate([
                spotrad, [getattr(pl_params, f'spotrad{spot_id}'),]])
            spotlat = np.concatenate([
                spotlat, [getattr(pl_params, f'spotlat{spot_id}'),]])
            spotlon = np.concatenate([
                spotlon, [getattr(pl_params, f'spotlon{spot_id}'),]])

        if pl_params.spotnpts is None:
            # Have a default spotnpts for fleck
            pl_params.spotnpts = 300

        fig = plt.figure(5307, figsize=(8, 6))
        plt.clf()
        ax = fig.gca()
        star = fleck.Star(spot_contrast=pl_params.spotcon,
                          u_ld=pl_params.u,
                          rotation_period=pl_params.spotrot)
        ax = star.plot(spotlon[:, None]*unit.deg,
                       spotlat[:, None]*unit.deg,
                       spotrad[:, None],
                       pl_params.spotstari*unit.deg,
                       planet=pl_params, time=pl_params.t0, ax=ax)

        if lc.white:
            fname_tag = 'white'
        else:
            ch_number = str(channel).zfill(len(str(lc.nchannel)))
            fname_tag = f'ch{ch_number}'
        fname = (f'figs{os.sep}fig5307_{fname_tag}_fleck_star_{fitter}'
                 + plots.figure_filetype)
        fig.savefig(meta.outputdir+fname, bbox_inches='tight', dpi=300)
        if not meta.hide_plots:
            plt.pause(0.2)


def plot_starry_star(lc, model, meta, fitter):
    """Plot the location and contrast of the starry star spots (Figs 5308)

    Parameters
    ----------
    lc : eureka.S5_lightcurve_fitting.lightcurve.LightCurve
        The lightcurve data object.
    model : eureka.S5_lightcurve_fitting.differentiable_models.CompositePyMC3Model  # noqa: E501
        The fitted composite model.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    fitter : str
        The name of the fitter (for plot filename).
    """
    for c in range(lc.nchannel_fitted):
        channel = lc.fitted_channels[c]
        if lc.nchannel_fitted > 1:
            chan = channel
        else:
            chan = 0

        # Initialize PlanetParams object
        pl_params = PlanetParams(model, 0, chan, eval=True)

        # create arrays to hold values
        spotrad = np.zeros(0)
        spotlat = np.zeros(0)
        spotlon = np.zeros(0)
        spotcon = np.zeros(0)

        for n in range(pl_params.nspots):
            # read radii, latitudes, longitudes, and contrasts
            if n > 0:
                spot_id = f'{n}'
            else:
                spot_id = ''
            spotrad = np.concatenate([
                spotrad, [getattr(pl_params, f'spotrad{spot_id}'),]])
            spotlat = np.concatenate([
                spotlat, [getattr(pl_params, f'spotlat{spot_id}'),]])
            spotlon = np.concatenate([
                spotlon, [getattr(pl_params, f'spotlon{spot_id}'),]])
            spotcon = np.concatenate([
                spotcon, [getattr(pl_params, f'spotcon{spot_id}'),]])

        # Apply some conversions since inputs are in fleck units
        spotrad *= 90
        spotcon = 1-spotcon

        if pl_params.spotnpts is None:
            # Have a default spotnpts for starry
            pl_params.spotnpts = 30

        # Initialize map object and add spots
        map = starry.Map(ydeg=pl_params.spotnpts,
                         inc=pl_params.spotstari)
        for n in range(pl_params.nspots):
            map.spot(contrast=spotcon[n], radius=spotrad[n],
                     lat=spotlat[n], lon=spotlon[n])

        fig = plt.figure(5308, figsize=(8, 6))
        plt.clf()
        ax = fig.gca()
        map.show(ax=ax)
        if lc.white:
            fname_tag = 'white'
        else:
            ch_number = str(channel).zfill(len(str(lc.nchannel)))
            fname_tag = f'ch{ch_number}'
        fname = (f'figs{os.sep}fig5308_{fname_tag}_starry_star_{fitter}'
                 + plots.figure_filetype)
        fig.savefig(meta.outputdir+fname, bbox_inches='tight', dpi=300)
        if not meta.hide_plots:
            plt.pause(0.2)
