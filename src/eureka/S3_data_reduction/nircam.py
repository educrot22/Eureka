# NIRCam specific rountines go here
import numpy as np
from astropy.io import fits
import astraeus.xarrayIO as xrio

from . import sigrej, background, optspex, straighten, plots_s3
from ..lib.util import read_time, supersample
from ..lib import meanerr as me

__all__ = ['read', 'straighten_trace', 'flag_ff', 'flag_bg', 'flag_bg_phot',
           'fit_bg', 'cut_aperture', 'standard_spectrum', 'clean_median_flux',
           'do_oneoverf_corr', 'calibrated_spectra',
           'residualBackground', 'lc_nodriftcorr']


def read(filename, data, meta, log):
    '''Reads single FITS file from JWST's NIRCam instrument.

    Parameters
    ----------
    filename : str
        Single filename to read.
    data : Xarray Dataset
        The Dataset object in which the fits data will stored.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    log : logedit.Logedit
        The current log.

    Returns
    -------
    data : Xarray Dataset
        The updated Dataset object with the fits data stored inside.
    meta : eureka.lib.readECF.MetaClass
        The updated metadata object.
    log : logedit.Logedit
        The current log.

    Notes
    -----
    History:

    - November 2012 Kevin Stevenson
        Initial version
    - May 2021 KBS
        Updated for NIRCam
    - July 2021
        Moved bjdtdb into here
    - Apr 20, 2022 Kevin Stevenson
        Convert to using Xarray Dataset
    '''
    hdulist = fits.open(filename)

    # Load master and science headers
    data.attrs['filename'] = filename
    data.attrs['mhdr'] = hdulist[0].header
    data.attrs['shdr'] = hdulist['SCI', 1].header

    data.attrs['intstart'] = data.attrs['mhdr']['INTSTART']-1
    data.attrs['intend'] = data.attrs['mhdr']['INTEND']

    sci = hdulist['SCI', 1].data
    err = hdulist['ERR', 1].data
    dq = hdulist['DQ', 1].data
    v0 = hdulist['VAR_RNOISE', 1].data

    try:
        data.attrs['intstart'] = data.attrs['mhdr']['INTSTART']-1
        data.attrs['intend'] = data.attrs['mhdr']['INTEND']
    except:
        # FINDME: Need to only catch the particular exception we expect
        log.writelog('  WARNING: Manually setting INTSTART to 0 and INTEND '
                     'to NINTS')
        data.attrs['intstart'] = 0
        data.attrs['intend'] = sci.shape[0]

    meta.filter = data.attrs['mhdr']['FILTER']

    if hdulist[0].header['CHANNEL'] == 'LONG':
        # Spectroscopy will have "LONG" as CHANNEL
        meta.photometry = False
        if not meta.poly_wavelength:
            # Use the FITS data
            wave_2d = hdulist['WAVELENGTH', 1].data
        elif meta.filter == 'F322W2':
            # The new way, using the polynomial model Everett Schlawin computed
            X = np.arange(hdulist['WAVELENGTH', 1].data.shape[1], dtype=float)
            if meta.wave_pixel_offset is not None:
                if meta.firstFile:
                    log.writelog('\n  Offsetting polynomial wavelength '
                                 f'solution by {meta.wave_pixel_offset} '
                                 'pixels.')
                X += meta.wave_pixel_offset
            Xprime = (X - 1571)/1000
            wave_2d = (3.9269369110332657
                       + 0.9811653393151226*Xprime
                       + 0.001666535535484272*Xprime**2
                       - 0.002874123523765872*Xprime**3)
            # Convert 1D array to 2D
            wave_2d = np.repeat(wave_2d[np.newaxis],
                                hdulist['WAVELENGTH', 1].data.shape[0], axis=0)
        elif meta.filter == 'F444W':
            # The new way, using the polynomial model Everett Schlawin computed
            X = np.arange(hdulist['WAVELENGTH', 1].data.shape[1], dtype=float)
            if meta.wave_pixel_offset is not None:
                if meta.firstFile:
                    log.writelog('\n  Offsetting polynomial wavelength '
                                 f'solution by {meta.wave_pixel_offset} '
                                 'pixels.')
                X += meta.wave_pixel_offset
            Xprime = (X - 852.0756)/1000
            wave_2d = (3.928041104137344
                       + 0.979649332832983*Xprime)
            # Convert 1D array to 2D
            wave_2d = np.repeat(wave_2d[np.newaxis],
                                hdulist['WAVELENGTH', 1].data.shape[0], axis=0)
        # Increase pixel resolution along cross-dispersion direction
        if meta.expand > 1:
            log.writelog(f'    Super-sampling y axis from {sci.shape[1]} ' +
                         f'to {sci.shape[1]*meta.expand} pixels...',
                         mute=(not meta.verbose))
            sci = supersample(sci, meta.expand, 'flux', axis=1)
            err = supersample(err, meta.expand, 'err', axis=1)
            dq = supersample(dq, meta.expand, 'cal', axis=1)
            v0 = supersample(v0, meta.expand, 'flux', axis=1)
            wave_2d = supersample(wave_2d, meta.expand, 'wave', axis=0)

    elif hdulist[0].header['CHANNEL'] == 'SHORT':
        # Photometry will have "SHORT" as CHANNEL
        meta.photometry = True
        # The DISPAXIS argument does not exist in the header of the photometry
        # data. Added it here so that code in other sections doesn't have to
        # be changed
        data.attrs['shdr']['DISPAXIS'] = 1

        # FINDME: make this better for all filters
        if meta.filter == 'F210M':
            # will be deleted at the end of S3
            wave_1d = np.ones_like(sci[0, 0]) * 2.095
            # Is used in S4 for plotting.
            meta.phot_wave = 2.095
        elif meta.filter == 'F187N':
            wave_1d = np.ones_like(sci[0, 0]) * 1.874
            meta.phot_wave = 1.874
        elif meta.filter in ['WLP4', 'F212N']:
            wave_1d = np.ones_like(sci[0, 0]) * 2.121
            meta.phot_wave = 2.121

    # Record integration mid-times in BMJD_TDB
    int_times = hdulist['INT_TIMES', 1].data
    if meta.time_file is not None:
        time = read_time(meta, data, log)
    elif len(int_times['int_mid_BJD_TDB']) == 0:
        # There is no time information in the simulated data
        if meta.firstFile:
            log.writelog('  WARNING: The timestamps for simulated data '
                         'are not in the .fits files, so using integration '
                         'number as the time value instead.')
        time = np.linspace(data.mhdr['EXPSTART'], data.mhdr['EXPEND'],
                           data.intend)
    else:
        time = int_times['int_mid_BJD_TDB']
    if len(time) > len(sci):
        # This line is needed to still handle the simulated data
        # which had the full time array for all segments
        time = time[data.attrs['intstart']:data.attrs['intend']]

    # Record units
    flux_units = data.attrs['shdr']['BUNIT']
    time_units = 'BMJD_TDB'
    wave_units = 'microns'

    if (meta.firstFile and meta.spec_hw == meta.spec_hw_range[0] and
            meta.bg_hw == meta.bg_hw_range[0]):
        # Only apply super-sampling expansion once
        meta.ywindow[0] *= meta.expand
        meta.ywindow[1] *= meta.expand

    data['flux'] = xrio.makeFluxLikeDA(sci, time, flux_units, time_units,
                                       name='flux')
    data['err'] = xrio.makeFluxLikeDA(err, time, flux_units, time_units,
                                      name='err')
    data['dq'] = xrio.makeFluxLikeDA(dq, time, "None", time_units,
                                     name='dq')
    data['v0'] = xrio.makeFluxLikeDA(v0, time, flux_units, time_units,
                                     name='v0')
    if not meta.photometry:
        data['wave_2d'] = (['y', 'x'], wave_2d)
        data['wave_2d'].attrs['wave_units'] = wave_units
    else:
        data['wave_1d'] = (['x'], wave_1d)
        data['wave_1d'].attrs['wave_units'] = wave_units
    # Initialize bad pixel mask (False = good, True = bad)
    data['mask'] = (['time', 'y', 'x'], np.zeros(data.flux.shape, dtype=bool))
    return data, meta, log


def flag_bg(data, meta, log):
    '''Outlier rejection of sky background along time axis.

    Parameters
    ----------
    data : Xarray Dataset
        The Dataset object.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    log : logedit.Logedit
        The current log.

    Returns
    -------
    data : Xarray Dataset
        The updated Dataset object with outlier background pixels flagged.
    '''
    log.writelog('  Performing background outlier rejection...',
                 mute=(not meta.verbose))

    size = data.mask.size
    prev_count = (~data.mask.values).sum()

    bgdata1 = data.flux[:, :meta.bg_y1]
    bgmask1 = data.mask[:, :meta.bg_y1]
    bgdata2 = data.flux[:, meta.bg_y2:]
    bgmask2 = data.mask[:, meta.bg_y2:]
    if meta.use_estsig:
        bgerr1 = np.median(data.err[:, :meta.bg_y1])
        bgerr2 = np.median(data.err[:, meta.bg_y2:])
        estsig1 = [bgerr1 for j in range(len(meta.bg_thresh))]
        estsig2 = [bgerr2 for j in range(len(meta.bg_thresh))]
    else:
        estsig1 = None
        estsig2 = None
    data['mask'][:, :meta.bg_y1] = sigrej.sigrej(bgdata1, meta.bg_thresh,
                                                 bgmask1, estsig1)
    data['mask'][:, meta.bg_y2:] = sigrej.sigrej(bgdata2, meta.bg_thresh,
                                                 bgmask2, estsig2)

    # Count difference in number of good pixels
    new_count = (~data.mask.values).sum()
    diff_count = prev_count - new_count
    perc_rej = 100*(diff_count/size)
    log.writelog(f'    Flagged {perc_rej:.6f}% of pixels as bad.',
                 mute=(not meta.verbose))

    return data


def flag_bg_phot(data, meta, log):
    '''Outlier rejection of sky background along time axis for photometry.

    Parameters
    ----------
    data : Xarray Dataset
        The Dataset object.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    log : logedit.Logedit
        The current log.

    Returns
    -------
    data : Xarray Dataset
        The updated Dataset object with outlier background pixels flagged.
    '''
    log.writelog('  Performing background outlier rejection...',
                 mute=(not meta.verbose))

    size = data.mask.size
    prev_count = (~data.mask.values).sum()

    # Figure out which pixels are outside of the source aperture
    x_indices, y_indices = np.meshgrid(np.arange(data.flux.shape[2]),
                                       np.arange(data.flux.shape[1]))
    mean_x = np.ma.median(data.centroid_x.values)
    mean_y = np.ma.median(data.centroid_y.values)
    distance = np.sqrt((x_indices-mean_x)**2 + (y_indices-mean_y)**2)
    outside_aper = distance > meta.photap

    # Do sigrej only on the pixels outside of the source aperture
    bgdata = data.flux.values[:, outside_aper]
    bgmask = data.mask.values[:, outside_aper]
    data.mask.values[:, outside_aper] = sigrej.sigrej(bgdata, meta.bg_thresh,
                                                      bgmask, None)

    # Count difference in number of good pixels
    new_count = (~data.mask.values).sum()
    diff_count = prev_count - new_count
    perc_rej = 100*(diff_count/size)
    log.writelog(f'    Flagged {perc_rej:.6f}% of pixels as bad.',
                 mute=(not meta.verbose))

    return data


def flag_ff(data, meta, log):
    '''Outlier rejection of full frame along time axis.
    For data with deep transits, there is a risk of masking good transit data.
    Proceed with caution.

    Parameters
    ----------
    data : Xarray Dataset
        The Dataset object.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    log : logedit.Logedit
        The current log.

    Returns
    -------
    data : Xarray Dataset
        The updated Dataset object with outlier pixels flagged.
    '''
    log.writelog('  Performing full frame outlier rejection...',
                 mute=(not meta.verbose))

    size = data.mask.size
    prev_count = (~data.mask.values).sum()

    # Compute new pixel mask
    data['mask'] = sigrej.sigrej(data.flux, meta.bg_thresh, data.mask, None)

    # Count difference in number of good pixels
    new_count = (~data.mask.values).sum()
    diff_count = prev_count - new_count
    perc_rej = 100*(diff_count/size)
    log.writelog(f'    Flagged {perc_rej:.6f}% of pixels as bad.',
                 mute=(not meta.verbose))

    return data


def fit_bg(dataim, datamask, n, meta, isplots=0):
    """Fit for a non-uniform background.

    Parameters
    ----------
    dataim : ndarray (2D)
        The 2D image array.
    datamask : ndarray (2D)
        A boolean array of which data (set to True) should be masked.
    n : int
        The current integration.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    isplots : int; optional
        The plotting verbosity, by default 0.

    Returns
    -------
    bg : ndarray (2D)
        The fitted background level.
    mask : ndarray (2D)
        The updated boolean mask after background subtraction, where True
        values should be masked.
    n : int
        The current integration number.
    """
    if meta.bg_dir == 'RxR':
        bg, mask = background.fitbg(dataim, meta, datamask, meta.bg_x1,
                                    meta.bg_x2, deg=meta.bg_deg,
                                    threshold=meta.p3thresh, isrotate=0,
                                    isplots=isplots)
    else:
        bg, mask = background.fitbg(dataim, meta, datamask, meta.bg_y1,
                                    meta.bg_y2, deg=meta.bg_deg,
                                    threshold=meta.p3thresh, isrotate=2,
                                    isplots=isplots)

    return bg, mask, n


def cut_aperture(data, meta, log):
    """Select the aperture region out of each trimmed image.

    Parameters
    ----------
    data : Xarray Dataset
        The Dataset object.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    log : logedit.Logedit
        The current log.

    Returns
    -------
    apdata : ndarray
        The flux values over the aperture region.
    aperr : ndarray
        The noise values over the aperture region.
    apmask : ndarray
        The mask values over the aperture region. True values should be masked.
    apbg : ndarray
        The background flux values over the aperture region.
    apv0 : ndarray
        The v0 values over the aperture region.
    apmedflux : ndarray
        The median flux over the aperture region.

    Notes
    -----
    History:

    - 2022-06-17, Taylor J Bell
        Initial version based on the code in s3_reduce.py
    """
    log.writelog('  Extracting aperture region...',
                 mute=(not meta.verbose))

    ap_y1 = int(meta.src_ypos-meta.spec_hw)
    ap_y2 = int(meta.src_ypos+meta.spec_hw+1)
    apdata = data.flux[:, ap_y1:ap_y2].values
    aperr = data.err[:, ap_y1:ap_y2].values
    apmask = data.mask[:, ap_y1:ap_y2].values
    apbg = data.bg[:, ap_y1:ap_y2].values
    apv0 = data.v0[:, ap_y1:ap_y2].values
    apmedflux = data.medflux[ap_y1:ap_y2].values

    return apdata, aperr, apmask, apbg, apv0, apmedflux


def standard_spectrum(data, meta, apdata, apmask, aperr):
    """Instrument wrapper for computing the standard box spectrum.

    Parameters
    ----------
    data : Xarray Dataset
        The Dataset object.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    apdata : ndarray
        The pixel values in the aperture region.
    apmask : ndarray
        The outlier mask in the aperture region. True where pixels should be
        masked.
    aperr : ndarray
        The noise values in the aperture region.

    Returns
    -------
    data : Xarray Dataset
        The updated Dataset object in which the spectrum data will stored.
    """

    # Create xarray
    coords = list(data.coords.keys())
    coords.remove('y')
    data['stdspec'] = (coords, np.zeros_like(data.flux[:, 0]))
    data['stdvar'] = (coords, np.zeros_like(data.flux[:, 0]))
    data['stdspec'].attrs['flux_units'] = \
        data.flux.attrs['flux_units']
    data['stdspec'].attrs['time_units'] = \
        data.flux.attrs['time_units']
    data['stdvar'].attrs['flux_units'] = \
        data.flux.attrs['flux_units']
    data['stdvar'].attrs['time_units'] = \
        data.flux.attrs['time_units']

    if meta.orders is None:
        # Compute standard box spectrum and variance without orders
        stdspec, stdvar = optspex.standard_spectrum(apdata, apmask, aperr)
        # Store results in data xarray
        data['stdspec'][:] = stdspec
        data['stdvar'][:] = stdvar
    else:
        for k, order in enumerate(meta.orders):
            # Compute standard box spectrum and variance with orders
            stdspec, stdvar = optspex.standard_spectrum(apdata[:, :, :, k],
                                                        apmask[:, :, :, k],
                                                        aperr[:, :, :, k])
            # Store results in data xarray
            data['stdspec'].sel(order=order)[:] = stdspec
            data['stdvar'].sel(order=order)[:] = stdvar

    return data


def clean_median_flux(data, meta, log, m):
    """Computes a median flux frame that is free of bad pixels.

    Parameters
    ----------
    data : Xarray Dataset
        The Dataset object.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    log : logedit.Logedit
        The current log.
    m : int
        The file number.

    Returns
    -------
    data : Xarray Dataset
        The updated Dataset object.
    """
    log.writelog('  Computing clean median frame...', mute=(not meta.verbose))

    # Compute median flux using masked arrays
    flux_ma = np.ma.masked_where(data.mask.values, data.flux.values)
    medflux = np.ma.median(flux_ma, axis=0)
    # Compute median error array
    err_ma = np.ma.masked_where(data.mask.values, data.err.values)
    mederr = np.ma.median(err_ma, axis=0)

    # Call subroutine
    clean_flux = optspex.get_clean(data, meta, log, medflux, mederr)

    # Assign (un)cleaned median frame to data object
    data['medflux'] = (['y', 'x'], clean_flux)
    data['medflux'].attrs['flux_units'] = data.flux.attrs['flux_units']

    if meta.isplots_S3 >= 3:
        plots_s3.median_frame(data, meta, m, clean_flux)

    return data


def do_oneoverf_corr(data, meta, i, star_pos_x, log):
    """
    Correcting for 1/f noise in each amplifier region by doing a row-by-row
    subtraction while avoiding pixels close to the star.

    Parameters
    ----------
    data : Xarray Dataset
        The Dataset object.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    i : int
        The current integration.
    star_pos_x : int
        The star position in columns (x dimension).
    log : logedit.Logedit
        The current log.

    Returns
    -------
    data : Xarray Dataset
        The updated Dataset object after the 1/f correction has been completed.
    """
    if i == 0:
        log.writelog('    Correcting for 1/f noise...',
                     mute=(not meta.verbose))

    # Let's first determine which amplifier regions are left in the frame.
    # For NIRCam: 4 amplifiers, 512 pixels in x dimension per amplifier
    # Every NIRCam subarray has 2048 pixels in the x dimension
    pxl_idxs = np.arange(2048)
    pxl_in_window_bool = np.zeros(2048, dtype=bool)
    # pxl_in_window_bool is True for pixels which weren't trimmed away
    # by meta.xwindow
    for p in pxl_idxs:
        if meta.xwindow[0] <= pxl_idxs[p] < meta.xwindow[1]:
            pxl_in_window_bool[p] = True
    ampl_used_bool = np.any(pxl_in_window_bool.reshape((4, 512)), axis=1)
    # Example: if only the middle two amplifier are left after trimming:
    # ampl_used = [False, True, True, False]

    # position of star before trimming
    star_pos_x_untrim = int(star_pos_x) + meta.xwindow[0]
    star_exclusion_area_untrim = \
        np.array([star_pos_x_untrim-meta.oneoverf_dist,
                  star_pos_x_untrim+meta.oneoverf_dist])

    use_cols = np.ones(2048, dtype=bool)
    for p in pxl_idxs:
        if star_exclusion_area_untrim[0] <= p < star_exclusion_area_untrim[1]:
            use_cols[p] = False
    use_cols = use_cols[meta.xwindow[0]:meta.xwindow[1]]
    # Array with bools checking if column should be used for
    # background subtraction

    edges_all = []
    flux_all = []
    err_all = []
    mask_all = []
    edges = np.array([[0, 512], [512, 1024], [1024, 1536], [1536, 2048]])

    # Let's go through each amplifier region
    for k in range(4):
        if not ampl_used_bool[k]:
            # Add a place-holder so indexing doesn't get messed up below
            edges_all.append([])
            flux_all.append([])
            err_all.append([])
            mask_all.append([])
            continue
        edge = edges[k] - meta.xwindow[0]
        edge[np.where(edge < 0)] = 0
        use_cols_temp = np.copy(use_cols)
        inds = np.arange(len(use_cols_temp))
        # Set False if columns are out of amplifier region
        use_cols_temp[np.logical_or(inds < edge[0], inds >= edge[1])] = False
        edges_all.append(edge)
        flux_all.append(data.flux.values[i][:, use_cols_temp])
        err_all.append(data.err.values[i][:, use_cols_temp])
        mask_all.append(data.mask.values[i][:, use_cols_temp])

    # Do odd even column subtraction
    odd_cols = data.flux.values[i, :, ::2]
    even_cols = data.flux.values[i, :, 1::2]
    use_cols_odd = use_cols[::2]
    use_cols_even = use_cols[1::2]
    odd_median = np.nanmedian(odd_cols[:, use_cols_odd])
    even_median = np.nanmedian(even_cols[:, use_cols_even])
    data.flux.values[i, :, ::2] -= odd_median
    data.flux.values[i, :, 1::2] -= even_median

    if meta.oneoverf_corr == 'meanerr':
        for j in range(128):
            for k in range(4):
                if ampl_used_bool[k]:
                    edges_temp = edges_all[k]
                    data.flux.values[i][j, edges_temp[0]:edges_temp[1]] -= \
                        me.meanerr(flux_all[k][j], err_all[k][j],
                                   mask=mask_all[k][j], err=False)
    elif meta.oneoverf_corr == 'median':
        for k in range(4):
            if ampl_used_bool[k]:
                edges_temp = edges_all[k]
                temp_vals = np.ma.masked_where(mask_all[k], flux_all[k])
                data.flux.values[i][:, edges_temp[0]:edges_temp[1]] -= \
                    np.ma.median(temp_vals, axis=1)[:, None]
    else:
        raise AssertionError(f'The 1/f correction method {meta.oneoverf_corr} '
                             'is not supported. Please choose between meanerr '
                             'or median.')

    return data


def calibrated_spectra(data, meta, log):
    """Modify data to compute calibrated spectra in units of mJy.

    Parameters
    ----------
    data : Xarray Dataset
        The Dataset object.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    log : logedit.Logedit
        The current log.

    Returns
    -------
    data : ndarray
        The flux values in mJy

    Notes
    -----
    History:

    - 2023-07-17, KBS
        Initial version.
    """
    # Convert from MJy/sr to mJy
    log.writelog("  Converting from MJy/sr to mJy...",
                 mute=(not meta.verbose))
    data['flux'].data *= 1e9*data.shdr['PIXAR_SR']
    data['err'].data *= 1e9*data.shdr['PIXAR_SR']
    data['v0'].data *= 1e9*data.shdr['PIXAR_SR']

    # Update units
    data['flux'].attrs["flux_units"] = 'mJy'
    data['err'].attrs["flux_units"] = 'mJy'
    data['v0'].attrs["flux_units"] = 'mJy'
    return data


def straighten_trace(data, meta, log, m):
    """Instrument-specific wrapper for straighten.straighten_trace

    Parameters
    ----------
    data : Xarray Dataset
            The Dataset object in which the fits data will stored.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    log : logedit.Logedit
        The open log in which notes from this step can be added.
    m : int
        The file number.

    Returns
    -------
    data : Xarray Dataset
        The updated Dataset object with the fits data stored inside.
    meta : eureka.lib.readECF.MetaClass
        The updated metadata object.
    """
    return straighten.straighten_trace(data, meta, log, m)


def residualBackground(data, meta, m, vmin=None, vmax=None):
    """Plot the median, BG-subtracted frame to study the residual BG region and
    aperture/BG sizes. (Fig 3304)

    Parameters
    ----------
    data : Xarray Dataset
        The Dataset object.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    m : int
        The file number.
    vmin : int; optional
        Minimum value of colormap. Default is None.
    vmax : int; optional
        Maximum value of colormap. Default is None.
    """
    plots_s3.residualBackground(data, meta, m, vmin=None, vmax=None)


def lc_nodriftcorr(spec, meta):
    '''Plot a 2D light curve without drift correction. (Fig 3101+3102)

    Fig 3101 uses a linear wavelength x-axis, while Fig 3102 uses a linear
    detector pixel x-axis.

    Parameters
    ----------
    spec : Xarray Dataset
        The Dataset object.
    meta : eureka.lib.readECF.MetaClass
        The metadata object.
    '''
    mad = meta.mad_s3[0]
    plots_s3.lc_nodriftcorr(meta, spec.wave_1d, spec.optspec,
                            optmask=spec.optmask, mad=mad)
