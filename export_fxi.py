import databroker
import datetime
import numpy as np
import prefect

from prefect import task, Flow

@task
def run_export_fxi():
    tiled_client = databroker.from_profile("nsls2", username=None)['fxi']
    scan_id = tiled_client[-1].start['scan_id']
    scan_type = tiled_client[-1].start['plan_name']
    logger = prefect.context.get("logger")
    logger.info(f"Scan ID: {scan_id}")
    logger.info(f"Scan Type: {scan_type}")
    export_single_scan(scan_id, tiled_client)


with Flow("export_fxi") as flow:
    run_export_fxi()


def is_legacy(start):
    """
    Check if a start document is from a legacy scan.
    """
    t_new = datetime.datetime(2021, 5, 1)
    t = start["time"] - 3600 * 60 * 4  # there are 4hour offset
    t = datetime.datetime.utcfromtimestamp(t)
    scan_type = start['plan_name']
    legacy_set = {'tomo_scan', 'fly_scan', 'xanes_scan', 'xanes_scan2'}
    return t < t_new and scan_type in legacy_set


def export_single_scan(scan_id=-1, tiled_client, binning=4, fpath=None):
    #raster_2d_2 scan calls export_raster_2D function even though export_raster_2D_2 function exists.
    # Legacy functions do not exist yet.
    start = tiled_client[scan_id].start
    scan_id = start["scan_id"]
    scan_type = start["plan_name"]
    export_function = f"export_{scan_type}_legacy" if is_legacy(start) else f"export_{scan_type}"
    assert export_function in locals().keys()
    locals()[export_function](start, tiled_client, fpath)


def export_tomo_scan(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    scan_type = "tomo_scan"
    scan_id = start["scan_id"]
    try:
        x_eng = start["XEng"]
    except:
        x_eng = start["x_ray_energy"]
    bkg_img_num = start["num_bkg_images"]
    dark_img_num = start["num_dark_images"]
    imgs_per_angle = start["plan_args"]["imgs_per_angle"]
    angle_i = start["plan_args"]["start"]
    angle_e = start["plan_args"]["stop"]
    angle_n = start["plan_args"]["num"]
    exposure_t = start["plan_args"]["exposure_time"]
    img = np.array(list(h.data("Andor_image", stream_name="primary")))
    img_tomo = np.median(img, axis=1)
    img_dark = np.array(list(h.data("Andor_image", stream_name="dark")))[0]
    img_bkg = np.array(list(h.data("Andor_image", stream_name="flat")))[0]

    img_dark_avg = np.median(img_dark, axis=0, keepdims=True)
    img_bkg_avg = np.median(img_bkg, axis=0, keepdims=True)
    img_angle = np.linspace(angle_i, angle_e, angle_n)

    fname = fpath + scan_type + "_id_" + str(scan_id) + ".h5"
    with h5py.File(fname, "w") as hf:
        hf.create_dataset("scan_id", data=scan_id)
        hf.create_dataset("X_eng", data=x_eng)
        hf.create_dataset("img_bkg", data=img_bkg)
        hf.create_dataset("img_dark", data=img_dark)
        hf.create_dataset("img_bkg_avg", data=img_bkg_avg.astype(np.float32))
        hf.create_dataset("img_dark_avg", data=img_dark_avg.astype(np.float32))
        hf.create_dataset("img_tomo", data=img_tomo)
        hf.create_dataset("angle", data=img_angle)
    try:
        write_lakeshore_to_file(start, fname)
    except:
        print("fails to write lakeshore info into {fname}")
    del img
    del img_tomo
    del img_dark
    del img_bkg


def export_fly_scan(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    uid = start["uid"]
    note = start["note"]
    scan_type = "fly_scan"
    scan_id = start["scan_id"]
    scan_time = start["time"]
    x_pos = h.table("baseline")["zps_sx"][1]
    y_pos = h.table("baseline")["zps_sy"][1]
    z_pos = h.table("baseline")["zps_sz"][1]
    r_pos = h.table("baseline")["zps_pi_r"][1]
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M

    x_eng = start["XEng"]
    img_angle = get_fly_scan_angle(uid)

    img_tomo = np.array(list(h.data("Andor_image", stream_name="primary")))[0]
    img_dark = np.array(list(h.data("Andor_image", stream_name="dark")))[0]
    img_bkg = np.array(list(h.data("Andor_image", stream_name="flat")))[0]

    img_dark_avg = np.median(img_dark, axis=0, keepdims=True)
    img_bkg_avg = np.median(img_bkg, axis=0, keepdims=True)

    fname = fpath + scan_type + "_id_" + str(scan_id) + ".h5"

    with h5py.File(fname, "w") as hf:
        hf.create_dataset("note", data=str(note))
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("scan_id", data=int(scan_id))
        hf.create_dataset("scan_time", data=scan_time)
        hf.create_dataset("X_eng", data=x_eng)
        hf.create_dataset("img_bkg", data=np.array(img_bkg, dtype=np.uint16))
        hf.create_dataset("img_dark", data=np.array(img_dark, dtype=np.uint16))
        hf.create_dataset("img_bkg_avg", data=np.array(img_bkg_avg, dtype=np.float32))
        hf.create_dataset("img_dark_avg", data=np.array(img_dark_avg, dtype=np.float32))
        hf.create_dataset("img_tomo", data=np.array(img_tomo, dtype=np.uint16))
        hf.create_dataset("angle", data=img_angle)
        hf.create_dataset("x_ini", data=x_pos)
        hf.create_dataset("y_ini", data=y_pos)
        hf.create_dataset("z_ini", data=z_pos)
        hf.create_dataset("r_ini", data=r_pos)
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(str(pxl_sz) + "nm"))
    """
    try:
        write_lakeshore_to_file(start, fname)
    except:
        print("fails to write lakeshore info into {fname}")
    """
    del img_tomo
    del img_dark
    del img_bkg


def export_fly_scan2(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    uid = start["uid"]
    note = start["note"]
    scan_type = "fly_scan2"
    scan_id = start["scan_id"]
    scan_time = start["time"]
    x_pos = h.table("baseline")["zps_sx"][1]
    y_pos = h.table("baseline")["zps_sy"][1]
    z_pos = h.table("baseline")["zps_sz"][1]
    r_pos = h.table("baseline")["zps_pi_r"][1]
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M

    try:
        x_eng = start["XEng"]
    except:
        x_eng = start["x_ray_energy"]
    chunk_size = start["chunk_size"]
    # sanity check: make sure we remembered the right stream name
    assert "zps_pi_r_monitor" in h.stream_names
    pos = h.table("zps_pi_r_monitor")
    #    imgs = list(h.data("Andor_image"))
    img_dark = np.array(list(h.data("Andor_image"))[-1][:])
    img_bkg = np.array(list(h.data("Andor_image"))[-2][:])
    s = img_dark.shape
    img_dark_avg = np.mean(img_dark, axis=0).reshape(1, s[1], s[2])
    img_bkg_avg = np.mean(img_bkg, axis=0).reshape(1, s[1], s[2])

    imgs = np.array(list(h.data("Andor_image"))[:-2])
    s1 = imgs.shape
    imgs = imgs.reshape([s1[0] * s1[1], s1[2], s1[3]])

    with db.reg.handler_context({"AD_HDF5": AreaDetectorHDF5TimestampHandler}):
        chunked_timestamps = list(h.data("Andor_image"))

    chunked_timestamps = chunked_timestamps[:-2]
    raw_timestamps = []
    for chunk in chunked_timestamps:
        raw_timestamps.extend(chunk.tolist())

    timestamps = convert_AD_timestamps(pd.Series(raw_timestamps))
    pos["time"] = pos["time"].dt.tz_localize("US/Eastern")

    img_day, img_hour = (
        timestamps.dt.day,
        timestamps.dt.hour,
    )
    img_min, img_sec, img_msec = (
        timestamps.dt.minute,
        timestamps.dt.second,
        timestamps.dt.microsecond,
    )
    img_time = (
        img_day * 86400 + img_hour * 3600 + img_min * 60 + img_sec + img_msec * 1e-6
    )
    img_time = np.array(img_time)

    mot_day, mot_hour = (
        pos["time"].dt.day,
        pos["time"].dt.hour,
    )
    mot_min, mot_sec, mot_msec = (
        pos["time"].dt.minute,
        pos["time"].dt.second,
        pos["time"].dt.microsecond,
    )
    mot_time = (
        mot_day * 86400 + mot_hour * 3600 + mot_min * 60 + mot_sec + mot_msec * 1e-6
    )
    mot_time = np.array(mot_time)

    mot_pos = np.array(pos["zps_pi_r"])
    offset = np.min([np.min(img_time), np.min(mot_time)])
    img_time -= offset
    mot_time -= offset
    mot_pos_interp = np.interp(img_time, mot_time, mot_pos)

    pos2 = mot_pos_interp.argmax() + 1
    # img_angle = mot_pos_interp[: pos2 - chunk_size]  # rotation angles
    img_angle = mot_pos_interp[:pos2]
    # img_tomo = imgs[: pos2 - chunk_size]  # tomo images
    img_tomo = imgs[:pos2]

    fname = fpath + scan_type + "_id_" + str(scan_id) + ".h5"

    with h5py.File(fname, "w") as hf:
        hf.create_dataset("note", data=str(note))
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("scan_id", data=int(scan_id))
        hf.create_dataset("scan_time", data=scan_time)
        hf.create_dataset("X_eng", data=x_eng)
        hf.create_dataset("img_bkg", data=np.array(img_bkg, dtype=np.uint16))
        hf.create_dataset("img_dark", data=np.array(img_dark, dtype=np.uint16))
        hf.create_dataset("img_bkg_avg", data=np.array(img_bkg_avg, dtype=np.float32))
        hf.create_dataset("img_dark_avg", data=np.array(img_dark_avg, dtype=np.float32))
        hf.create_dataset("img_tomo", data=np.array(img_tomo, dtype=np.uint16))
        hf.create_dataset("angle", data=img_angle)
        hf.create_dataset("x_ini", data=x_pos)
        hf.create_dataset("y_ini", data=y_pos)
        hf.create_dataset("z_ini", data=z_pos)
        hf.create_dataset("r_ini", data=r_pos)
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(str(pxl_sz) + "nm"))

    try:
        write_lakeshore_to_file(start, fname)
    except:
        print("fails to write lakeshore info into {fname}")

    del img_tomo
    del img_dark
    del img_bkg
    del imgs


def export_xanes_scan(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M
    scan_type = start["plan_name"]
    #    scan_type = 'xanes_scan'
    uid = start["uid"]
    note = start["note"]
    scan_id = start["scan_id"]
    scan_time = start["time"]
    try:
        x_eng = start["XEng"]
    except:
        x_eng = start["x_ray_energy"]
    chunk_size = start["chunk_size"]
    num_eng = start["num_eng"]

    img_xanes = np.array(list(h.data("Andor_image", stream_name="primary")))
    img_xanes_avg = np.mean(img_xanes, axis=1)
    img_dark = np.array(list(h.data("Andor_image", stream_name="dark")))
    img_dark_avg = np.mean(img_dark, axis=1)
    img_bkg = np.array(list(h.data("Andor_image", stream_name="flat")))
    img_bkg_avg = np.mean(img_bkg, axis=1)

    eng_list = list(start["eng_list"])

    img_xanes_norm = (img_xanes_avg - img_dark_avg) * 1.0 / (img_bkg_avg - img_dark_avg)
    img_xanes_norm[np.isnan(img_xanes_norm)] = 0
    img_xanes_norm[np.isinf(img_xanes_norm)] = 0
    fname = fpath + scan_type + "_id_" + str(scan_id) + ".h5"
    with h5py.File(fname, "w") as hf:
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("scan_id", data=scan_id)
        hf.create_dataset("note", data=str(note))
        hf.create_dataset("scan_time", data=scan_time)
        hf.create_dataset("X_eng", data=eng_list)
        hf.create_dataset("img_bkg", data=np.array(img_bkg_avg, dtype=np.float32))
        hf.create_dataset("img_dark", data=np.array(img_dark_avg, dtype=np.float32))
        hf.create_dataset("img_xanes", data=np.array(img_xanes_norm, dtype=np.float32))
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")

    try:
        write_lakeshore_to_file(start, fname)
    except:
        print("fails to write lakeshore info into {fname}")

    del (
        img_dark,
        img_dark_avg,
        img_bkg,
        img_bkg_avg,
        img_xanes,
        img_xanes_avg,
        img_xanes_norm,
    )


def export_xanes_scan_img_only(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M
    scan_type = start["plan_name"]
    #    scan_type = 'xanes_scan'
    uid = start["uid"]
    note = start["note"]
    scan_id = start["scan_id"]
    scan_time = start["time"]
    try:
        x_eng = start["XEng"]
    except:
        x_eng = start["x_ray_energy"]
    chunk_size = start["chunk_size"]
    num_eng = start["num_eng"]

    img_xanes = np.array(list(h.data("Andor_image", stream_name="primary")))
    img_xanes_avg = np.mean(img_xanes, axis=1)
    img_dark = np.array(list(h.data("Andor_image", stream_name="dark")))
    img_dark_avg = np.mean(img_dark, axis=1)
    img_bkg = np.ones(img_xanes.shape)
    img_bkg_avg = np.ones(img_dark_avg.shape)

    eng_list = list(start["eng_list"])

    img_xanes_norm = (img_xanes_avg - img_dark_avg) * 1.0
    img_xanes_norm[np.isnan(img_xanes_norm)] = 0
    img_xanes_norm[np.isinf(img_xanes_norm)] = 0
    fname = fpath + scan_type + "_id_" + str(scan_id) + "_img_only.h5"
    with h5py.File(fname, "w") as hf:
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("scan_id", data=scan_id)
        hf.create_dataset("note", data=str(note))
        hf.create_dataset("scan_time", data=scan_time)
        hf.create_dataset("X_eng", data=eng_list)
        hf.create_dataset("img_bkg", data=np.array(img_bkg_avg, dtype=np.float32))
        hf.create_dataset("img_dark", data=np.array(img_dark_avg, dtype=np.float32))
        hf.create_dataset("img_xanes", data=np.array(img_xanes_norm, dtype=np.float32))
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")

    try:
        write_lakeshore_to_file(start, fname)
    except:
        print("fails to write lakeshore info into {fname}")

    del (
        img_dark,
        img_dark_avg,
        img_bkg,
        img_bkg_avg,
        img_xanes,
        img_xanes_avg,
        img_xanes_norm,
    )


def export_z_scan(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M
    scan_type = start["plan_name"]
    scan_id = start["scan_id"]
    uid = start["uid"]
    try:
        x_eng = start["XEng"]
    except:
        x_eng = start["x_ray_energy"]
    num = start["plan_args"]["steps"]
    chunk_size = start["plan_args"]["chunk_size"]
    note = start["plan_args"]["note"] if start["plan_args"]["note"] else "None"
    img = np.array(list(h.data("Andor_image")))
    img_zscan = np.mean(img[:num], axis=1)
    img_bkg = np.mean(img[num], axis=0, keepdims=True)
    img_dark = np.mean(img[-1], axis=0, keepdims=True)
    img_norm = (img_zscan - img_dark) / (img_bkg - img_dark)
    img_norm[np.isnan(img_norm)] = 0
    img_norm[np.isinf(img_norm)] = 0
    #    fn = start['plan_args']['fn']
    fname = fpath + scan_type + "_id_" + str(scan_id) + ".h5"
    with h5py.File(fname, "w") as hf:
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("scan_id", data=scan_id)
        hf.create_dataset("note", data=str(note))
        hf.create_dataset("X_eng", data=x_eng)
        hf.create_dataset("img_bkg", data=img_bkg.astype(np.float32))
        hf.create_dataset("img_dark", data=img_dark.astype(np.float32))
        hf.create_dataset("img", data=img_zscan.astype(np.float32))
        hf.create_dataset("img_norm", data=img_norm.astype(np.float32))
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")

    try:
        write_lakeshore_to_file(start, fname)
    except:
        print("fails to write lakeshore info into {fname}")

    del img, img_zscan, img_bkg, img_dark, img_norm


def export_z_scan2(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M
    scan_type = start["plan_name"]
    scan_id = start["scan_id"]
    uid = start["uid"]
    try:
        x_eng = start["XEng"]
    except:
        x_eng = start["x_ray_energy"]
    num = start["plan_args"]["steps"]
    chunk_size = start["plan_args"]["chunk_size"]
    note = start["plan_args"]["note"] if start["plan_args"]["note"] else "None"
    img = np.mean(np.array(list(h.data("Andor_image"))), axis=1)
    img = np.squeeze(img)
    img_dark = img[0]
    l1 = np.arange(1, len(img), 2)
    l2 = np.arange(2, len(img), 2)

    img_zscan = img[l1]
    img_bkg = img[l2]

    img_norm = (img_zscan - img_dark) / (img_bkg - img_dark)
    img_norm[np.isnan(img_norm)] = 0
    img_norm[np.isinf(img_norm)] = 0

    fname = fpath + scan_type + "_id_" + str(scan_id) + ".h5"
    with h5py.File(fname, "w") as hf:
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("scan_id", data=scan_id)
        hf.create_dataset("note", data=str(note))
        hf.create_dataset("X_eng", data=x_eng)
        hf.create_dataset(
            "img_bkg", data=np.array(img_bkg.astype(np.float32), dtype=np.float32)
        )
        hf.create_dataset("img_dark", data=img_dark.astype(np.float32))
        hf.create_dataset("img", data=img_zscan.astype(np.float32))
        hf.create_dataset(
            "img_norm", data=np.array(img_norm.astype(np.float32), dtype=np.float32)
        )
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")

    try:
        write_lakeshore_to_file(start, fname)
    except:
        print("fails to write lakeshore info into {fname}")

    del img, img_zscan, img_bkg, img_dark, img_norm


def export_test_scan(start, tiled_client,  fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M
    import tifffile

    scan_type = start["plan_name"]
    scan_id = start["scan_id"]
    uid = start["uid"]
    try:
        x_eng = start["XEng"]
    except:
        x_eng = start["x_ray_energy"]
    num = start["plan_args"]["num_img"]
    num_bkg = start["plan_args"]["num_bkg"]
    note = start["plan_args"]["note"] if start["plan_args"]["note"] else "None"
    img = np.squeeze(np.array(list(h.data("Andor_image"))))
    assert len(img.shape) == 3, "load test_scan fails..."
    img_test = img[:num]
    img_bkg = np.mean(img[num : num + num_bkg], axis=0, keepdims=True)
    img_dark = np.mean(img[-num_bkg:], axis=0, keepdims=True)
    img_norm = (img_test - img_dark) / (img_bkg - img_dark)
    img_norm[np.isnan(img_norm)] = 0
    img_norm[np.isinf(img_norm)] = 0
    #    fn = start['plan_args']['fn']
    fname = fpath + scan_type + "_id_" + str(scan_id) + ".h5"
    fname_tif = fpath + scan_type + "_id_" + str(scan_id) + ".tif"
    with h5py.File(fname, "w") as hf:
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("scan_id", data=scan_id)
        hf.create_dataset("X_eng", data=x_eng)
        hf.create_dataset("note", data=str(note))
        hf.create_dataset("img_bkg", data=img_bkg)
        hf.create_dataset("img_dark", data=img_dark)
        hf.create_dataset("img", data=np.array(img_test, dtype=np.float32))
        hf.create_dataset("img_norm", data=np.array(img_norm, dtype=np.float32))
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")
    #    tifffile.imsave(fname_tif, img_norm)

    try:
        write_lakeshore_to_file(start, fname)
    except:
        print("fails to write lakeshore info into {fname}")

    del img, img_test, img_bkg, img_dark, img_norm


def export_count(start, tiled_client, fpath=None):
    """
    load images (e.g. RE(count([Andor], 10)) ) and save to .h5 file
    """
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    try:
        zp_z_pos = h.table("baseline")["zp_z"][1]
        DetU_z_pos = h.table("baseline")["DetU_z"][1]
        M = (DetU_z_pos / zp_z_pos - 1) * 10.0
        pxl_sz = 6500.0 / M
    except:
        M = 0
        pxl_sz = 0
        print("fails to calculate magnification and pxl size")

    uid = start["uid"]
    det = start["detectors"][0]
    img = get_img(start, det)
    scan_id = start["scan_id"]
    fn = fpath + "count_id_" + str(scan_id) + ".h5"
    with h5py.File(fn, "w") as hf:
        hf.create_dataset("img", data=img.astype(np.float32))
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("scan_id", data=scan_id)
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")
    try:
        write_lakeshore_to_file(start, fn)
    except:
        print("fails to write lakeshore info into {fname}")


def export_delay_count(start, tiled_client, fpath=None):
    """
    load images (e.g. RE(count([Andor], 10)) ) and save to .h5 file
    """
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    try:
        zp_z_pos = h.table("baseline")["zp_z"][1]
        DetU_z_pos = h.table("baseline")["DetU_z"][1]
        M = (DetU_z_pos / zp_z_pos - 1) * 10.0
        pxl_sz = 6500.0 / M
    except:
        M = 0
        pxl_sz = 0
        print("fails to calculate magnification and pxl size")

    uid = start["uid"]
    det = start["detectors"][0]
    img = get_img(start, det)
    scan_id = start["scan_id"]
    fn = fpath + "count_id_" + str(scan_id) + ".h5"
    with h5py.File(fn, "w") as hf:
        hf.create_dataset("img", data=img.astype(np.float32))
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("scan_id", data=scan_id)
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")
    try:
        write_lakeshore_to_file(start, fn)
    except:
        print("fails to write lakeshore info into {fname}")


def export_delay_scan(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    det = start["detectors"][0]
    scan_type = start["plan_name"]
    scan_id = start["scan_id"]
    uid = start["uid"]
    x_eng = start["XEng"]
    note = start["plan_args"]["note"] if start["plan_args"]["note"] else "None"
    mot_name = start["plan_args"]["motor"]
    mot_start = start["plan_args"]["start"]
    mot_stop = start["plan_args"]["stop"]
    mot_steps = start["plan_args"]["steps"]
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M
    if det == "detA1" or det == "Andor":
        img = get_img(start, det)
        fname = fpath + scan_type + "_id_" + str(scan_id) + ".h5"
        with h5py.File(fname, "w") as hf:
            hf.create_dataset("img", data=np.array(img, dtype=np.float32))
            hf.create_dataset("uid", data=uid)
            hf.create_dataset("scan_id", data=scan_id)
            hf.create_dataset("X_eng", data=x_eng)
            hf.create_dataset("note", data=str(note))
            hf.create_dataset("start", data=mot_start)
            hf.create_dataset("stop", data=mot_stop)
            hf.create_dataset("steps", data=mot_steps)
            hf.create_dataset("motor", data=mot_name)
            hf.create_dataset("Magnification", data=M)
            hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")
        try:
            write_lakeshore_to_file(start, fname)
        except:
            print("fails to write lakeshore info into {fname}")
    else:
        print("no image stored in this scan")


def export_multipos_count(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    scan_type = start["plan_name"]
    scan_id = start["scan_id"]
    uid = start["uid"]
    num_dark = start["num_dark_images"]
    num_of_position = start["num_of_position"]
    note = start["note"]
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M

    img_raw = list(h.data("Andor_image"))
    img_dark = np.squeeze(np.array(img_raw[:num_dark]))
    img_dark_avg = np.mean(img_dark, axis=0, keepdims=True)
    num_repeat = np.int(
        (len(img_raw) - 10) / num_of_position / 2
    )  # alternatively image and background

    tot_img_num = num_of_position * 2 * num_repeat
    s = img_dark.shape
    img_group = np.zeros([num_of_position, num_repeat, s[1], s[2]], dtype=np.float32)

    for j in range(num_repeat):
        index = num_dark + j * num_of_position * 2
        print(f"processing #{index} / {tot_img_num}")
        for i in range(num_of_position):
            tmp_img = np.array(img_raw[index + i * 2])
            tmp_bkg = np.array(img_raw[index + i * 2 + 1])
            img_group[i, j] = (tmp_img - img_dark_avg) / (tmp_bkg - img_dark_avg)
    # fn = os.getcwd() + "/"
    fname = fpath + scan_type + "_id_" + str(scan_id) + ".h5"
    with h5py.File(fname, "w") as hf:
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("scan_id", data=scan_id)
        hf.create_dataset("note", data=str(note))
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")
        for i in range(num_of_position):
            hf.create_dataset(f"img_pos{i+1}", data=np.squeeze(img_group[i]))
    try:
        write_lakeshore_to_file(start, fname)
    except:
        print("fails to write lakeshore info into {fname}")


def export_grid2D_rel(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M
    uid = start["uid"]
    note = start["note"]
    scan_type = "grid2D_rel"
    scan_id = start["scan_id"]
    scan_time = start["time"]
    x_eng = start["XEng"]
    num1 = start["plan_args"]["num1"]
    num2 = start["plan_args"]["num2"]
    img = np.squeeze(np.array(list(h.data("Andor_image"))))

    fname = scan_type + "_id_" + str(scan_id)
    # cwd = os.getcwd()
    cwd = fpath
    try:
        os.mkdir(cwd + f"{fname}")
    except:
        print(cwd + f"{name} existed")
    fout = cwd + f"{fname}"
    for i in range(num1):
        for j in range(num2):
            fname_tif = fout + f"_({ij}).tif"
            img = Image.fromarray(img[i * num1 + j])
            img.save(fname_tif)


def export_raster_2D_2(start, tiled_client, binning=4, fpath=None):
    import tifffile
    from skimage import io

    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    uid = start["uid"]
    note = start["note"]
    scan_type = "grid2D_rel"
    scan_id = start["scan_id"]
    scan_time = start["time"]
    num_dark = 5
    num_bkg = start["plan_args"]["num_bkg"]
    x_eng = start["XEng"]
    x_range = start["plan_args"]["x_range"]
    y_range = start["plan_args"]["y_range"]
    img_sizeX = start["plan_args"]["img_sizeX"]
    img_sizeY = start["plan_args"]["img_sizeY"]
    pix = start["plan_args"]["pxl"]
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M

    img_raw = np.squeeze(np.array(list(h.data("Andor_image"))))
    img_dark_avg = np.mean(img_raw[:num_dark], axis=0, keepdims=True)
    s = img_dark_avg.shape
    # img_bkg_avg = np.mean(img_raw[-num_bkg:], axis=0, keepdims = True)
    # img = img_raw[num_dark:-num_bkg]

    num_img = (x_range[1] - x_range[0] + 1) * (y_range[1] - y_range[0] + 1)
    img = np.zeros([num_img, s[1], s[2]])
    for i in range(num_img):
        index = num_dark + i * num_bkg + i
        img_bkg_avg = np.mean(
            img_raw[index + 1 : index + 1 + num_bkg], axis=0, keepdims=True
        )
        img[i] = (img_raw[index] - img_dark_avg) / (img_bkg_avg - img_dark_avg)

    s = img.shape

    x_num = round((x_range[1] - x_range[0]) + 1)
    y_num = round((y_range[1] - y_range[0]) + 1)
    x_list = np.linspace(x_range[0], x_range[1], x_num)
    y_list = np.linspace(y_range[0], y_range[1], y_num)
    row_size = y_num * s[1]
    col_size = x_num * s[2]
    img_patch = np.zeros([1, row_size, col_size])
    index = 0
    pos_file_for_print = np.zeros([x_num * y_num, 4])
    pos_file = ["cord_x\tcord_y\tx_pos_relative\ty_pos_relative\n"]
    index = 0
    for i in range(int(x_num)):
        for j in range(int(y_num)):
            img_patch[0, j * s[1] : (j + 1) * s[1], i * s[2] : (i + 1) * s[2]] = img[
                index
            ]
            pos_file_for_print[index] = [
                x_list[i],
                y_list[j],
                x_list[i] * pix * img_sizeX / 1000,
                y_list[j] * pix * img_sizeY / 1000,
            ]
            pos_file.append(
                f"{x_list[i]:3.0f}\t{y_list[j]:3.0f}\t{x_list[i]*pix*img_sizeX/1000:3.3f}\t\t{y_list[j]*pix*img_sizeY/1000:3.3f}\n"
            )
            index = index + 1
    s = img_patch.shape
    img_patch_bin = bin_ndarray(
        img_patch, new_shape=(1, int(s[1] / binning), int(s[2] / binning))
    )
    fout_h5 = fpath + f"raster2D_scan_{scan_id}_binning_{binning}.h5"
    fout_tiff = fpath + f"raster2D_scan_{scan_id}_binning_{binning}.tiff"
    fout_txt = fpath + f"raster2D_scan_{scan_id}_cord.txt"
    print(f"{pos_file_for_print}")
    io.imsave(fout_tiff, np.array(img_patch_bin[0], dtype=np.float32))
    with open(f"{fout_txt}", "w+") as f:
        f.writelines(pos_file)
    # tifffile.imsave(fout_tiff, np.array(img_patch_bin, dtype=np.float32))
    num_img = int(x_num) * int(y_num)
    # cwd = os.getcwd()
    # new_dir = f"{cwd}/raster_scan_{scan_id}"
    new_dir = fpath + f"raster_scan_{scan_id}"
    if not os.path.exists(new_dir):
        os.mkdir(new_dir)
    """
    s = img.shape
    tmp = bin_ndarray(img, new_shape=(s[0], int(s[1]/binning), int(s[2]/binning)))
    for i in range(num_img):  
        fout = f'{new_dir}/img_{i:02d}_binning_{binning}.tiff'
        print(f'saving {fout}')
        tifffile.imsave(fout, np.array(tmp[i], dtype=np.float32))
    """
    fn_h5_save = f"{new_dir}/img_{i:02d}_binning_{binning}.h5"
    with h5py.File(fn_h5_save, "w") as hf:
        hf.create_dataset("img_patch", data=np.array(img_patch_bin, np.float32))
        hf.create_dataset("img", data=np.array(img, np.float32))
        hf.create_dataset("img_dark", data=np.array(img_dark_avg, np.float32))
        hf.create_dataset("img_bkg", data=np.array(img_bkg_avg, np.float32))
        hf.create_dataset("XEng", data=x_eng)
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")
    try:
        write_lakeshore_to_file(start, fn_h5_save)
    except:
        print(f"fails to write lakeshore info into {fn_h5_save}")


def export_raster_2D(start, tiled_client, binning=4, fpath=None):
    import tifffile

    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"

    uid = start["uid"]
    note = start["note"]
    scan_type = "grid2D_rel"
    scan_id = start["scan_id"]
    scan_time = start["time"]
    num_dark = start["num_dark_images"]
    num_bkg = start["num_bkg_images"]
    x_eng = start["XEng"]
    x_range = start["plan_args"]["x_range"]
    y_range = start["plan_args"]["y_range"]
    img_sizeX = start["plan_args"]["img_sizeX"]
    img_sizeY = start["plan_args"]["img_sizeY"]
    pix = start["plan_args"]["pxl"]
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M

    img_raw = np.squeeze(np.array(list(h.data("Andor_image"))))
    img_dark_avg = np.mean(img_raw[:num_dark], axis=0, keepdims=True)
    img_bkg_avg = np.mean(img_raw[-num_bkg:], axis=0, keepdims=True)
    img = img_raw[num_dark:-num_bkg]
    s = img.shape
    img = (img - img_dark_avg) / (img_bkg_avg - img_dark_avg)
    x_num = round((x_range[1] - x_range[0]) + 1)
    y_num = round((y_range[1] - y_range[0]) + 1)
    x_list = np.linspace(x_range[0], x_range[1], x_num)
    y_list = np.linspace(y_range[0], y_range[1], y_num)
    row_size = y_num * s[1]
    col_size = x_num * s[2]
    img_patch = np.zeros([1, row_size, col_size])
    index = 0
    pos_file_for_print = np.zeros([x_num * y_num, 4])
    pos_file = ["cord_x\tcord_y\tx_pos_relative\ty_pos_relative\n"]
    index = 0
    for i in range(int(x_num)):
        for j in range(int(y_num)):
            img_patch[0, j * s[1] : (j + 1) * s[1], i * s[2] : (i + 1) * s[2]] = img[
                index
            ]
            pos_file_for_print[index] = [
                x_list[i],
                y_list[j],
                x_list[i] * pix * img_sizeX / 1000,
                y_list[j] * pix * img_sizeY / 1000,
            ]
            pos_file.append(
                f"{x_list[i]:3.0f}\t{y_list[j]:3.0f}\t{x_list[i]*pix*img_sizeX/1000:3.3f}\t\t{y_list[j]*pix*img_sizeY/1000:3.3f}\n"
            )
            index = index + 1
    s = img_patch.shape
    img_patch_bin = bin_ndarray(
        img_patch, new_shape=(1, int(s[1] / binning), int(s[2] / binning))
    )
    fout_h5 = fpath + f"raster2D_scan_{scan_id}_binning_{binning}.h5"
    fout_tiff = fpath + f"raster2D_scan_{scan_id}_binning_{binning}.tiff"
    fout_txt = fpath + f"raster2D_scan_{scan_id}_cord.txt"
    print(f"{pos_file_for_print}")
    with open(f"{fout_txt}", "w+") as f:
        f.writelines(pos_file)
    tifffile.imsave(fout_tiff, np.array(img_patch_bin, dtype=np.float32))
    num_img = int(x_num) * int(y_num)
    # cwd = os.getcwd()
    # new_dir = f"{cwd}/raster_scan_{scan_id}"
    new_dir = fpath + f"raster_scan_{scan_id}"
    if not os.path.exists(new_dir):
        os.mkdir(new_dir)
    """
    s = img.shape
    tmp = bin_ndarray(img, new_shape=(s[0], int(s[1]/binning), int(s[2]/binning)))
    for i in range(num_img):  
        fout = f'{new_dir}/img_{i:02d}_binning_{binning}.tiff'
        print(f'saving {fout}')
        tifffile.imsave(fout, np.array(tmp[i], dtype=np.float32))
    """
    fn_h5_save = f"{new_dir}/img_{i:02d}_binning_{binning}.h5"
    with h5py.File(fn_h5_save, "w") as hf:
        hf.create_dataset("img_patch", data=np.array(img_patch_bin, np.float32))
        hf.create_dataset("img", data=np.array(img, np.float32))
        hf.create_dataset("img_dark", data=np.array(img_dark_avg, np.float32))
        hf.create_dataset("img_bkg", data=np.array(img_bkg_avg, np.float32))
        hf.create_dataset("XEng", data=x_eng)
        hf.create_dataset("Magnification", data=M)
        hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")
    try:
        write_lakeshore_to_file(start, fn_h5_save)
    except:
        print(f"fails to write lakeshore info into {fn_h5_save}")


def export_multipos_2D_xanes_scan2(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    scan_type = start["plan_name"]
    uid = start["uid"]
    note = start["note"]
    scan_id = start["scan_id"]
    scan_time = start["time"]
    #    x_eng = start['x_ray_energy']
    x_eng = start["XEng"]
    chunk_size = start["chunk_size"]
    chunk_size = start["num_bkg_images"]
    num_eng = start["num_eng"]
    num_pos = start["num_pos"]
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M
    try:
        repeat_num = start["plan_args"]["repeat_num"]
    except:
        repeat_num = 1

    img_xanes = np.array(list(h.data("Andor_image", stream_name="primary")))
    img_dark = np.array(list(h.data("Andor_image", stream_name="dark")))
    img_bkg = np.array(list(h.data("Andor_image", stream_name="flat")))

    img_xanes = np.mean(img_xanes, axis=1)
    img_dark = np.mean(img_dark, axis=1)
    img_bkg = np.mean(img_bkg, axis=1)

    eng_list = list(start["eng_list"])

    for repeat in range(repeat_num):  # revised here
        try:
            print(f"repeat: {repeat}")
            id_s = int(repeat * num_eng)
            id_e = int((repeat + 1) * num_eng)
            img_x = img_xanes[id_s * num_pos : id_e * num_pos]  # xanes image
            img_b = img_bkg[id_s:id_e]  # bkg image
            # save data
            # fn = os.getcwd() + "/"
            fn = fpath
            for j in range(num_pos):
                img_p = img_x[j::num_pos]
                img_p_n = (img_p - img_dark) / (img_b - img_dark)
                fname = (
                    f"{fn}{scan_type}_id_{scan_id}_repeat_{repeat:02d}_pos_{j:02d}.h5"
                )
                print(f"saving {fname}")
                with h5py.File(fname, "w") as hf:
                    hf.create_dataset("uid", data=uid)
                    hf.create_dataset("scan_id", data=scan_id)
                    hf.create_dataset("note", data=str(note))
                    hf.create_dataset("scan_time", data=scan_time)
                    hf.create_dataset("X_eng", data=eng_list)
                    hf.create_dataset(
                        "img_bkg", data=np.array(img_bkg, dtype=np.float32)
                    )
                    hf.create_dataset(
                        "img_dark", data=np.array(img_dark, dtype=np.float32)
                    )
                    hf.create_dataset(
                        "img_xanes", data=np.array(img_p_n, dtype=np.float32)
                    )
                    hf.create_dataset("Magnification", data=M)
                    hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")
                """
                try:
                    write_lakeshore_to_file(start, fname)
                except:
                    print("fails to write lakeshore info into {fname}")
                """
        except:
            print(f"fails in export repeat# {repeat}")
    del img_xanes
    del img_bkg
    del img_dark
    del img_p, img_p_n


def export_multipos_2D_xanes_scan3(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M
    scan_type = start["plan_name"]
    uid = start["uid"]
    note = start["note"]
    scan_id = start["scan_id"]
    scan_time = start["time"]
    #    x_eng = start['x_ray_energy']
    x_eng = start["XEng"]
    chunk_size = start["chunk_size"]
    chunk_size = start["num_bkg_images"]
    num_eng = start["num_eng"]
    num_pos = start["num_pos"]
    #    repeat_num = start['plan_args']['repeat_num']
    imgs = np.array(list(h.data("Andor_image")))
    imgs = np.mean(imgs, axis=1)
    img_dark = imgs[0]
    eng_list = list(start["eng_list"])
    s = imgs.shape

    img_xanes = np.zeros([num_pos, num_eng, imgs.shape[1], imgs.shape[2]])
    img_bkg = np.zeros([num_eng, imgs.shape[1], imgs.shape[2]])

    index = 1
    for i in range(num_eng):
        for j in range(num_pos):
            img_xanes[j, i] = imgs[index]
            index += 1

    img_bkg = imgs[-num_eng:]

    for i in range(num_eng):
        for j in range(num_pos):
            img_xanes[j, i] = (img_xanes[j, i] - img_dark) / (img_bkg[i] - img_dark)
    # save data
    # fn = os.getcwd() + "/"
    fn = fpath
    for j in range(num_pos):
        fname = f"{fn}{scan_type}_id_{scan_id}_pos_{j}.h5"
        with h5py.File(fname, "w") as hf:
            hf.create_dataset("uid", data=uid)
            hf.create_dataset("scan_id", data=scan_id)
            hf.create_dataset("note", data=str(note))
            hf.create_dataset("scan_time", data=scan_time)
            hf.create_dataset("X_eng", data=eng_list)
            hf.create_dataset("img_bkg", data=np.array(img_bkg, dtype=np.float32))
            hf.create_dataset("img_dark", data=np.array(img_dark, dtype=np.float32))
            hf.create_dataset(
                "img_xanes", data=np.array(img_xanes[j], dtype=np.float32)
            )
            hf.create_dataset("Magnification", data=M)
            hf.create_dataset("Pixel Size", data=str(pxl_sz) + "nm")

        try:
            write_lakeshore_to_file(start, fname)
        except:
            print("fails to write lakeshore info into {fname}")
    del img_xanes
    del img_bkg
    del img_dark
    del imgs


def export_user_fly_only(start, tiled_client, fpath=None):
    if fpath is None:
        fpath = "./"
    else:
        if not fpath[-1] == "/":
            fpath += "/"
    uid = start["uid"]
    note = start["note"]
    scan_type = start["plan_name"]
    scan_id = start["scan_id"]
    scan_time = start["time"]
    dark_scan_id = start["plan_args"]["dark_scan_id"]
    bkg_scan_id = start["plan_args"]["bkg_scan_id"]
    x_pos = h.table("baseline")["zps_sx"][1]
    y_pos = h.table("baseline")["zps_sy"][1]
    z_pos = h.table("baseline")["zps_sz"][1]
    r_pos = h.table("baseline")["zps_pi_r"][1]

    try:
        x_eng = start["XEng"]
    except:
        x_eng = start["x_ray_energy"]
    # sanity check: make sure we remembered the right stream name
    assert "zps_pi_r_monitor" in h.stream_names
    pos = h.table("zps_pi_r_monitor")
    imgs = np.array(list(h.data("Andor_image")))

    s1 = imgs.shape
    chunk_size = s1[1]
    imgs = imgs.reshape(-1, s1[2], s1[3])

    # load darks and bkgs
    img_dark = np.array(list(db[dark_scan_id].data("Andor_image")))[0]
    img_bkg = np.array(list(db[bkg_scan_id].data("Andor_image")))[0]
    s = img_dark.shape
    img_dark_avg = np.mean(img_dark, axis=0).reshape(1, s[1], s[2])
    img_bkg_avg = np.mean(img_bkg, axis=0).reshape(1, s[1], s[2])

    with db.reg.handler_context({"AD_HDF5": AreaDetectorHDF5TimestampHandler}):
        chunked_timestamps = list(h.data("Andor_image"))

    raw_timestamps = []
    for chunk in chunked_timestamps:
        raw_timestamps.extend(chunk.tolist())

    timestamps = convert_AD_timestamps(pd.Series(raw_timestamps))
    pos["time"] = pos["time"].dt.tz_localize("US/Eastern")

    img_day, img_hour = (
        timestamps.dt.day,
        timestamps.dt.hour,
    )
    img_min, img_sec, img_msec = (
        timestamps.dt.minute,
        timestamps.dt.second,
        timestamps.dt.microsecond,
    )
    img_time = (
        img_day * 86400 + img_hour * 3600 + img_min * 60 + img_sec + img_msec * 1e-6
    )
    img_time = np.array(img_time)

    mot_day, mot_hour = (
        pos["time"].dt.day,
        pos["time"].dt.hour,
    )
    mot_min, mot_sec, mot_msec = (
        pos["time"].dt.minute,
        pos["time"].dt.second,
        pos["time"].dt.microsecond,
    )
    mot_time = (
        mot_day * 86400 + mot_hour * 3600 + mot_min * 60 + mot_sec + mot_msec * 1e-6
    )
    mot_time = np.array(mot_time)

    mot_pos = np.array(pos["zps_pi_r"])
    offset = np.min([np.min(img_time), np.min(mot_time)])
    img_time -= offset
    mot_time -= offset
    mot_pos_interp = np.interp(img_time, mot_time, mot_pos)

    pos2 = mot_pos_interp.argmax() + 1
    img_angle = mot_pos_interp[: pos2 - chunk_size]  # rotation angles
    img_tomo = imgs[: pos2 - chunk_size]  # tomo images

    fname = fpath + "fly_scan_id_" + str(scan_id) + ".h5"

    with h5py.File(fname, "w") as hf:
        hf.create_dataset("note", data=str(note))
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("scan_id", data=int(scan_id))
        hf.create_dataset("scan_time", data=scan_time)
        hf.create_dataset("X_eng", data=x_eng)
        hf.create_dataset("img_bkg", data=np.array(img_bkg, dtype=np.uint16))
        hf.create_dataset("img_dark", data=np.array(img_dark, dtype=np.uint16))
        hf.create_dataset("img_bkg_avg", data=np.array(img_bkg_avg, dtype=np.float32))
        hf.create_dataset("img_dark_avg", data=np.array(img_dark_avg, dtype=np.float32))
        hf.create_dataset("img_tomo", data=np.array(img_tomo, dtype=np.uint16))
        hf.create_dataset("angle", data=img_angle)
        hf.create_dataset("x_ini", data=x_pos)
        hf.create_dataset("y_ini", data=y_pos)
        hf.create_dataset("z_ini", data=z_pos)
        hf.create_dataset("r_ini", data=r_pos)

    try:
        write_lakeshore_to_file(start, fname)
    except:
        print("fails to write lakeshore info into {fname}")

    del img_tomo
    del img_dark
    del img_bkg
    del imgs


def export_scan_change_expo_time(start, tiled_client,  fpath=None, save_range_x=[], save_range_y=[]):
    from skimage import io

    if fpath is None:
        fpath = os.getcwd()
    if not fpath[-1] == "/":
        fpath += "/"
    scan_id = start["scan_id"]
    fpath += f"scan_{scan_id}/"
    fpath_t1 = fpath + "t1/"
    fpath_t2 = fpath + "t2/"
    os.makedirs(fpath, exist_ok=True, mode=0o777)
    os.makedirs(fpath_t1, exist_ok=True, mode=0o777)
    os.makedirs(fpath_t2, exist_ok=True, mode=0o777)

    zp_z_pos = h.table("baseline")["zp_z"][1]
    DetU_z_pos = h.table("baseline")["DetU_z"][1]
    M = (DetU_z_pos / zp_z_pos - 1) * 10.0
    pxl_sz = 6500.0 / M
    scan_type = start["plan_name"]
    uid = start["uid"]
    note = start["plan_args"]["note"]

    scan_time = start["time"]
    x_eng = start["x_ray_energy"]
    t1 = start["plan_args"]["t1"]
    t2 = start["plan_args"]["t2"]

    img_sizeX = start["plan_args"]["img_sizeX"]
    img_sizeY = start["plan_args"]["img_sizeY"]
    pxl = start["plan_args"]["pxl"]
    step_x = img_sizeX * pxl
    step_y = img_sizeY * pxl

    x_range = start["plan_args"]["x_range"]
    y_range = start["plan_args"]["y_range"]

    imgs = list(h.data("Andor_image"))
    s = imgs[0].shape

    if len(save_range_x) == 0:
        save_range_x = [0, s[0]]
    if len(save_range_y) == 0:
        save_range_y = [0, s[1]]

    img_dark_t1 = np.median(np.array(imgs[:5]), axis=0)
    img_dark_t2 = np.median(np.array(imgs[5:10]), axis=0)
    imgs = imgs[10:]

    nx = np.abs(x_range[1] - x_range[0] + 1)
    ny = np.abs(y_range[1] - y_range[0] + 1)
    pos_x = np.zeros(nx * ny)
    pos_y = pos_x.copy()

    idx = 0

    for ii in range(nx):
        if not ii % 100:
            print(f"nx = {ii}")
        for jj in range(ny):
            if not jj % 10:
                print(f"ny = {jj}")
            pos_x[idx] = ii * step_x
            pos_y[idx] = jj * step_y
            idx += 1
            id_c = ii * ny * (5 + 5 + 2) + jj * (5 + 5 + 2)
            img_t1 = imgs[id_c]
            img_t2 = imgs[id_c + 1]
            img_bkg_t1 = imgs[(id_c + 2) : (id_c + 7)]
            img_bkg_t1 = np.median(img_bkg_t1, axis=0)
            img_bkg_t2 = imgs[(id_c + 7) : (id_c + 12)]
            img_bkg_t2 = np.median(img_bkg_t2, axis=0)

            img_t1_n = (img_t1 - img_dark_t1) / (img_bkg_t1 - img_dark_t1)
            img_t2_n = (img_t2 - img_dark_t2) / (img_bkg_t2 - img_dark_t2)

            fsave_t1 = fpath_t1 + f"img_t1_{idx:05d}.tiff"
            fsave_t2 = fpath_t2 + f"img_t2_{idx:05d}.tiff"

            im1 = img_t1_n[
                0, save_range_x[0] : save_range_x[1], save_range_y[0] : save_range_y[1]
            ]
            im2 = img_t2_n[
                0, save_range_x[0] : save_range_x[1], save_range_y[0] : save_range_y[1]
            ]
            io.imsave(fsave_t1, im1.astype(np.float32))
            io.imsave(fsave_t2, im2.astype(np.float32))
    with h5py.File(fpath, "w") as hf:
        hf.create_dataset("scan_id", data=scan_id)
        hf.create_dataset("scan_type", data=scan_type)
        hf.create_dataset("uid", data=uid)
        hf.create_dataset("pxl_sz", data=pxl_sz)
        hf.create_dataset("note", data=note)
        hf.create_dataset("XEng", data=x_eng)
        hf.create_dataset("pos_x", data=pos_x)
        hf.create_dataset("pos_y", data=pos_y)

