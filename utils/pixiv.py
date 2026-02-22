import io
import json
import zipfile

from PIL import Image

import exception


async def ugoria_merge(bot, id) -> tuple[bytes, str]:
    ugo_resp = await bot.client.get(f"https://www.pixiv.net/ajax/illust/{id}/ugoira_meta")
    if ugo_resp.status == 200:
        ugo_json_resp = json.loads(await ugo_resp.text())
        ugo_zip_resp = await bot.client.get(ugo_json_resp["body"]["originalSrc"])
        if ugo_zip_resp.status == 200:
            frames = {f["file"]: f["delay"] for f in ugo_json_resp["body"]["frames"]}
            zipcontent = await ugo_zip_resp.read()
            with zipfile.ZipFile(io.BytesIO(zipcontent)) as zf:
                files = zf.namelist()
                images = []
                durations = []
                width = 0
                height = 0
                for file in files:
                    f = io.BytesIO(zf.read(file))
                    im = Image.open(fp=f)
                    width = max(im.width, width)
                    height = max(im.height, height)
                    images.append(im)
                    durations.append(int(frames[file]))

                first_im = images.pop(0)
                image = io.BytesIO()
                first_im.save(
                    image,
                    format="webp",
                    save_all=True,
                    append_images=images,
                    duration=durations,
                    lossless=True,
                    quality=100,
                )
                image = image.getvalue()
                image_name = f"ugoria_{id}.webp"

                return image, image_name
        else:
            raise exception.RequestFailed("request to pixiv ugoria zip failed")
    else:
        raise exception.RequestFailed("request to pixiv ugoria api failed")


async def pixiv_ajax_get(bot, link: str, image_num: int | None) -> tuple[dict, io.BytesIO, str]:
    """
    Fetch image from a Pixiv post.

    Args:
        bot: The ArtBot instance with client attribute
        link: Pixiv post URL
        image_num: 1-indexed image number (default: 1)

    Returns:
        tuple: (ajax_resp, image_bytes, image_filename)
    """
    id = link.split("/")[-1].split("?", 1)[0].split("#", 1)[0]
    resp = await bot.client.get(f"https://www.pixiv.net/ajax/illust/{id}")
    if resp.status == 200:
        ajax_resp = json.loads(await resp.text())
        if ajax_resp["body"]["aiType"] > 1:
            raise exception.AIImageFound("pixiv ai image")
        if ajax_resp["body"]["illustType"] != 2:
            image_link = ajax_resp["body"]["urls"]["original"]
            temp = ajax_resp["body"]["urls"]["original"].split("/")
            image_name = temp[len(temp) - 1]
            if image_num:
                image_link = image_link.replace("_p0_", f"_p{image_num-1}_")
            image_req = await bot.client.get(image_link)
            if image_req.status == 200:
                image = await image_req.read()
            else:
                raise exception.RequestFailed("request to pixiv image failed")
        else:
            image, image_name = await ugoria_merge(bot, id)
    return ajax_resp, io.BytesIO(image), image_name
