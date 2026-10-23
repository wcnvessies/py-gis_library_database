"""Collection of basic mapping functions."""

import io
import logging
import os
import random
from datetime import datetime, timedelta
from pathlib import Path

import mercantile
import numpy as np
import PIL.Image
import requests

logger = logging.getLogger("")


def _get_url(host, route, tile, options, switch_xy=False):
    """Compose the url for the tile to request.

    Input:  host  = webserver host name
            route = route to the tile request
            tile  = mercantile.tile object
            options = optional request parameters
            switch_xy = bool, switch the tile.x and tile.y in request (Arcgis only). Default=False
    Output: full url of request

    Author: R.A. van der Hout
    Date  : 2023-04-11
    """
    if switch_xy:
        params = f"/{tile.z}/{tile.y}/{tile.x}.png"
    else:
        params = f"/{tile.z}/{tile.x}/{tile.y}.png"
    return f"{host}{route}{params}{options}"


def _match_maptype(maptype, maptypes, mapdefault):
    """Match the maptype input with the available maptypes"""
    # First exact match
    if result := [m for m in maptypes if maptype.lower() == m.lower()]:
        return result[0]
    # Than fuzzy match
    if result := [m for m in maptypes if maptype.lower() in m.lower()]:
        if len(result) > 1:
            logger.info(f"More results are found: {result}, used first")
        maptype = result[0]
    else:
        maptype = mapdefault
    return maptype


def get_map_image(
    server_name: str,
    maptype: str,
    qk: str,
    cacheDir: str,
    useCache: bool = True,
    maxAgeDays: int = 365,
):
    """Read the map file from the webserver or from cache.

    Input:  server_name = str, name of tile webserver:  'seamap', 'openstreetmap' or 'image'
            maptype     = str, type of image. Only for seamap: 'lowpaper', 'fullpaper', 'hybridpaper', 'fullhybridpaper'
            qk          = str, tile quadkey code to read
            cacheDir    = str, directory for caching the maptiles. Default='temp_cache/maps'
            useCache    = bool, flag for using the cache. Default=True
            maxAgeDays  = int, maximum age of cached files
            api_key     = str, 'seamap' api key

    Output: img     = PIL image object of read tile
            fname   = filename of image object (stored in cache)

    Remarks:
    - Openseamap is not responsive now (sends empty tiles). Als with modified header (as Android mobile)
    - For Openstreetmap the header is modified to prevent blockage when too much tiles are requested (thanks to W. Vessies)
    - More tile servers can be adressed (Arcgis) but are not neccesary now

    Author: R.A. van der Hout, W. Vessies
    Date  : 2023-04-11
    """
    # Inits
    server_name = server_name.lower()
    maptype = maptype.lower()
    headers, route, options = ("", "", "")
    switch_xy = False

    # Convert the quadkey code to a tile
    tile = mercantile.quadkey_to_tile(qk)

    # Shortcuts
    if "image" in server_name:
        server_name = "arcgis"
        maptype = "world_imagery"

    useragent = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"

    match server_name:
        case "opentopomap":
            server = random.choice(["a", "b", "c"])
            host = f"https://{server}.tile.opentopomap.org"

            headers = {"User-Agent": useragent}
            maptype = ""

        case "openstreetmap" | "osm":
            maptype = "mapnik"
            server = random.choice(["a", "b", "c"])
            headers = {"User-Agent": useragent}
            host = f"http://{server}.tile.openstreetmap.org"

        case "openseamap":
            host = "http://tiles.openseamap.org"
            maptype = ""
            headers = {"User-Agent": useragent}
            route = "/seamark"

        case "arcgis":
            host = "http://server.arcgisonline.com"
            maptypes = [
                "NatGeo_World_Map",
                "USA_Topo_Maps",
                "World_Imagery",
                "World_Physical_Map",
                "World_Shaded_Relief",
                "World_Street_Map",
                "World_Terrain_Base",
                "World_Topo_Map",
                "Specialty/World_Navigation_Charts",
            ]
            maptype = _match_maptype(maptype, maptypes, "World_imagery")
            route = f"/ArcGIS/rest/services/{maptype}/MapServer/tile/"
            switch_xy = True

        case _:
            logger.warning("Error! Wrong input")
            return None, None

    # Set cache dir and filename
    fdir = Path(cacheDir).joinpath(server_name, maptype)
    # Compose url
    url = _get_url(host, route, tile, options, switch_xy=switch_xy)
    # Get the image
    img, fname = _get_map(url, headers, fdir, qk, useCache, maxAgeDays)
    if img is None:
        logger.warning(f"No image is retrieved from: {server_name}")

    return img, fname


def _get_map(url, headers, fdir, qk, useCache, maxAgeDays):
    """Read/get the map image data."""
    # Defaults
    img = None
    # Get the map
    fname = fdir.joinpath(f"{qk}.png")
    present = _check_cache(fdir, fname, maxAgeDays) if useCache else False
    if present and useCache:
        img = PIL.Image.open(fname)
    else:
        response = requests.get(url, headers=headers, stream=True)
        # Check valid response
        if response.status_code != 200:
            logger.error(
                f"Error in retrieving map. Status Code= {response.status_code}"
            )
            return img, fname

        img = PIL.Image.open(io.BytesIO(response.content))
        if useCache and img.getbbox():  # A not filled image has no getbbox value
            img.save(fname)
    return img, fname


def _check_cache(fdir: Path, fname: Path, maxAgeDays: int) -> bool:

    fdir.mkdir(parents=True, exist_ok=True)
    present = os.path.isfile(fname)
    if present:
        # f_size = os.path.getsize(fname)
        f_time = datetime.fromtimestamp(os.path.getctime(fname))  # noqa DTZ006
        f_age = datetime.now() - f_time  # noqa DTZ005
        if f_age > timedelta(days=maxAgeDays):  # or f_size < 3000:
            os.remove(fname)
            present = False
            logger.info(f"Removed cached file: {fname.name}")
    return present


def check_cache_age(cacheDir: str | Path, maxAgeDays: int = 30) -> None:

    # Collect the files
    files = Path(cacheDir).glob("*")
    today = datetime.now()  # noqa DTZ005
    for file in files:
        modified_date = datetime.fromtimestamp(os.path.getmtime(file))  # noqa DTZ006
        age = today - modified_date
        if age.days > maxAgeDays:
            logger.info(f"Removed old cachefile: {file.name}")
            os.remove(file)


def set_colors_to_transparant(img, rgb_transp=None):

    if rgb_transp is None:
        rgb_transp = [(0, 0, 0), (255, 255, 255)]

    # Convert to RGBA colors
    img = img.convert("RGBA")
    datas = img.getdata()
    newData = []

    # collect rgb colors to be transparant
    R, G, B = set(), set(), set()
    for col in rgb_transp:
        R.add(col[0])
        G.add(col[1])
        B.add(col[2])

    # filter + set transparant
    for item in datas:
        if item[0] in R and item[1] in G and item[2] in B:
            newData.append((255, 255, 255, 0))
        else:
            newData.append(item)
    img.putdata(newData)
    return img


def merge_qk_named_maps(
    qk_img_list: list, images: list | None = None
) -> tuple[PIL.Image.Image, mercantile.LngLatBbox]:

    # https://stackoverflow.com/questions/30227466/combine-several-images-horizontally-with-python

    # TODO CHECK the sizes to be equal !

    tile_codes = [tuple(mercantile.quadkey_to_tile(Path(f).stem)) for f in qk_img_list]

    # Get bounds (west, south, east, north)
    bnds = np.array([tuple(mercantile.bounds(*tl)) for tl in tile_codes])
    new_bounds = mercantile.LngLatBbox(
        bnds[:, 0].min(),
        bnds[:, 1].min(),
        bnds[:, 2].max(),
        bnds[:, 3].max(),
    )

    x_arr = np.array([f[0] for f in tile_codes])
    y_arr = np.array([f[1] for f in tile_codes])
    x_uniq = np.unique(x_arr)
    y_uniq = np.unique(y_arr)

    if images is None:
        # Read from file
        images = [PIL.Image.open(x) for x in qk_img_list]

    widths, heights = zip(*(i.size for i in images), strict=False)

    # ASSUMING every tile has the same dimensions
    total_width = widths[0] * len(x_uniq)  # sum(widths)
    max_height = heights[0] * len(y_uniq)  # max(heights)

    # Get the relative number
    x_offs = x_arr - x_arr.min()
    y_offs = y_arr - y_arr.min()

    # Dimension the new merged image
    new_im = PIL.Image.new("RGB", (total_width, max_height))

    # Fill the new merged image
    for n, img in enumerate(images):
        x_sz, y_sz = img.size
        new_im.paste(img, (x_offs[n] * x_sz, y_offs[n] * y_sz))

    return new_im, new_bounds


def getMap(
    server_name: str,
    maptype: str,
    qkeys: list,
    cacheDir: str = "temp_cache/maps",
    useCache: bool = True,
    maxAgeDays: int = 365,
) -> tuple[PIL.Image.Image, mercantile.LngLatBbox] | tuple[None, None]:

    # Inits
    if not isinstance(qkeys, list):
        qkeys = [qkeys]

    # Set/create cache directory
    cacheDir = Path(cacheDir)
    cacheDir.mkdir(parents=True, exist_ok=True)

    # Loop through the quadkeys
    fnames = []
    images = []
    for qk in qkeys:
        img, fname = get_map_image(
            server_name,
            maptype,
            qk,
            cacheDir,
            useCache=useCache,
            maxAgeDays=maxAgeDays,
        )
        if img is None:
            print("No images retieved from server. Stopped querying.")
            break
        fnames.append(fname)
        images.append(img)
    if images:
        # Merge images directly
        return merge_qk_named_maps(qk_img_list=fnames, images=images)
    else:
        return None, None
