"""
The functions of the new crawler projects
"""

import re
import os
import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

from curl_cffi import requests as res
from lxml import html
from ebooklib import epub

common_headers: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
}

html_name_match = re.compile("([0-9]+).(htm)")
img_name_match = re.compile("[0-9]+.(jpg|png|jpeg)")


def re_search(pattern: re.Pattern, text: str) -> re.Match:
    """Search pattern in text, assert a match exists, then return it."""
    match = pattern.search(text)
    assert match is not None, f"Pattern {pattern.pattern!r} not found in {text!r}"
    return match


def re_match(pattern: re.Pattern, text: str) -> re.Match:
    """Match pattern against text from start, assert a match exists, then return it."""
    match = pattern.match(text)
    assert match is not None, f"Pattern {pattern.pattern!r} does not match {text!r}"
    return match


class ContentPage:
    """
    A class represents every pages on the novel menu.
    """

    def __init__(self, href: str, title: str, idx: int, content: str) -> None:
        self.xhtml = epub.EpubHtml(
            title=title, file_name=href, media_type="xhtml", content=content
        )
        self.idx = idx


class ImagePage(ContentPage):
    """
    A class represents pages containing images.
    """

    def __init__(self, href: str, title: str, idx: int, content: str, imagelist: list[epub.EpubImage]) -> None:
        super().__init__(href, title, idx, content)
        self.imagelist = imagelist


def book_title_list(max_number: int = 0, crawl_delay: float = 5) -> int:
    con = sqlite3.connect("book_title_list.db")
    cur = con.cursor()
    cur.execute(
        """CREATE TABLE IF NOT EXISTS book
        (id INTEGER PRIMARY KEY, 
         title TEXT, 
         author TEXT,
         status BOOLEAN);"""
    )
    con.commit()
    start_number = (cur.execute("SELECT max(id) FROM book").fetchone()[0] or 0) + 1

    def mark_empty(book_id: int) -> None:
        """打印一条"空"记录，标记该编号没有找到可入库的信息。"""
        print([book_id, "空", "", 0])

    res = []
    for i in range(start_number, start_number + max_number):
        url_base = f"https://www.wenku8.net/novel/{i//1000}/{i}/"
        url = f"{url_base}index.htm"
        data = get_data(url)
        title_nodes = data.xpath('//*[@id="title"]/text()')
        if not title_nodes:
            mark_empty(i)
            continue
        title = title_nodes[0]
        info_nodes = data.xpath('//*[@id="info"]/text()')
        if not info_nodes:
            mark_empty(i)
            continue
        author = info_nodes[0][3:]
        ccss = data.cssselect(".ccss")
        if not ccss:
            print(f"{title} no content.")
            continue
        check = ccss[0]
        check_link = check.cssselect("a")
        if not check_link:
            mark_empty(i)
            continue
        check_href = check_link[0].get("href")
        check_data = get_data(f"{url_base}{check_href}")
        content_texts = check_data.xpath('//*[@id="content"]/text()')
        copyright_msg = "因版权问题，文库不再提供该小说的阅读！"
        if any(copyright_msg in t for t in content_texts):
            status = 0
        else:
            status = 1
        res.append([i, title, author, status])
        print([i, title, author, status])

        time.sleep(crawl_delay)

    cur.executemany("INSERT INTO book VALUES(?,?,?,?)", res)
    con.commit()
    con.close()

    return start_number + max_number - 1


def _get_response(url: str, headers: dict[str, str], max_retries: int = 5) -> res.Response:
    """请求 URL 并返回响应；模拟 Chrome 的 TLS 指纹以绕过 Cloudflare 拦截。"""
    for attempt in range(max_retries):
        try:
            with res.Session(impersonate="chrome") as s:
                return s.get(url=url, headers=headers, timeout=(2, 10))
        except Exception:
            if attempt == max_retries - 1:
                raise
    raise RuntimeError("unreachable")


def fetch(url: str, headers: dict[str, str] = common_headers) -> bytes:
    return _get_response(url, headers).content


def _decode_response(resp: res.Response) -> str:
    """将响应字节按正确编码解码为文本。

    wenku8 页面是 GBK 编码，但 lxml 直接按字节解析时可能误判编码，
    导致 "encoding error: input conversion failed" 报错。这里优先使用
    Content-Type 头或 HTML meta 声明的 charset；严格解码失败时按
    UTF-8 -> GBK 做容错解码，并选替换字符最少的结果（页面偶发的
    非法字节如 0xFE 0x82 会变成 U+FFFD，不影响整体解析）。
    """
    content = resp.content
    encodings = []
    if resp.charset_encoding:
        encodings.append(resp.charset_encoding)
    head = content[:8192].decode("ascii", errors="ignore")
    m = re.search(r'charset\s*=\s*["\']?([\w-]+)', head, re.I)
    if m:
        encodings.append(m.group(1))
    encodings += ["utf-8", "gbk"]

    # 1) 严格解码：能完整解码的编码直接用
    for enc in dict.fromkeys(encodings):
        try:
            return content.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue

    # 2) 容错解码：选替换字符最少的编码，坏字节变成 U+FFFD
    best = None
    for enc in dict.fromkeys(encodings):
        try:
            decoded = content.decode(enc, errors="replace")
        except LookupError:
            continue
        if best is None or decoded.count("\ufffd") < best.count("\ufffd"):
            best = decoded
    return best if best is not None else content.decode("utf-8", errors="replace")


def get_data(url: str, headers: dict[str, str] = common_headers) -> html.HtmlElement:
    return html.fromstring(_decode_response(_get_response(url, headers)))


def form_menu(data: html.HtmlElement) -> dict[str, list]:
    items = data.cssselect(".vcss, .ccss")
    res = dict()
    idx = None
    for item in items:
        classes = item.get("class")
        if classes is not None and "vcss" in classes.split():
            idx = item.text_content()
            res[idx] = []
        elif classes is not None and "ccss" in classes.split():
            if idx is None:
                print(res)
                raise ValueError("The first item of the list is not the volume")
            if item.text_content() != "\xa0":
                chapter_link = item.cssselect("a")[0]
                res[idx].append(chapter_link)
    return res


def get_content_with_images(idx: int, url: str, title: str) -> ContentPage:
    href = f"{re_search(html_name_match, url).group(1)}.xhtml"
    data = get_data(url)
    content_tags = data.xpath('//*[@id="content"]')
    if not content_tags:
        raise ValueError(f"Content not found in {url!r}")
    content_tag = content_tags[0]

    # 查找 #content 内的所有图片
    images = content_tag.cssselect("img")

    if images:
        # --- 含图片的章节（文字+图片混合）---
        # 将图片 src 从完整 URL 改为仅文件名（EPUB 内嵌资源引用用）
        img_infos = []
        for img in images:
            src = img.get("src")
            filename = re_search(img_name_match, src).group()
            img.set("src", filename)
            img_infos.append((src, filename))

        # 保留完整的 HTML 结构（文字 + 图片引用）
        html_str = str(html.tostring(content_tag, encoding="unicode"))
        html_str = html_str.replace("\xa0\xa0\xa0\xa0", "\xa0\xa0")
        html_str = html_str.replace("\xa0\xa0\xa0", "\xa0\xa0")
        content = html_str[78 : len(html_str) - 6]

        # 并发下载图片
        res = [epub.EpubImage()] * len(img_infos)
        with ThreadPoolExecutor(max_workers=min(len(img_infos), 20)) as t:
            obj_list = []
            for idx_i, (src, filename) in enumerate(img_infos):
                obj = t.submit(get_single_picture, idx_i, src, filename)
                obj_list.append(obj)
            for future in as_completed(obj_list):
                res_tmp = future.result()
                res[res_tmp[0]] = res_tmp[1]

        return ImagePage(href, title, idx, content, res)
    else:
        # --- 纯文字章节 ---
        html_str = str(html.tostring(content_tag, encoding="unicode"))
        html_str = html_str.replace("\xa0\xa0\xa0\xa0", "\xa0\xa0")
        html_str = html_str.replace("\xa0\xa0\xa0", "\xa0\xa0")
        content = html_str[78 : len(html_str) - 6]
        return ContentPage(href, title, idx, content)


def get_single_picture(idx: int, url: str, title: str) -> tuple[int, epub.EpubImage]:
    data = fetch(url)
    pic = epub.EpubImage()
    pic.file_name = title
    pic.media_type = f"image/{re_match(img_name_match, title).group(1)}"
    pic.content = data
    return (idx, pic)



def book_init(title: str, author: str) -> epub.EpubBook:
    book = epub.EpubBook()
    book.set_identifier("BlueRain77")
    book.set_title(title)
    book.add_author(author)
    book.set_language("zh")

    return book


def get_ebook(id: int, headers: dict[str, str] = common_headers, output_dir: str = "epub_output", crawl_delay: float = 5) -> None:
    """
    Main function of getting ebook.

    Args:
        id: Book ID on wenku8.
        headers: HTTP request headers.
        output_dir: Relative path to store the generated EPUB file. Defaults to "epub_output".
    """
    os.makedirs(output_dir, exist_ok=True)
    url_base = f"https://www.wenku8.net/novel/{id//1000}/{id}/"
    url_cover = f"https://img.wenku8.com/image/{id//1000}/{id}/{id}s.jpg"

    data = get_data(f"{url_base}index.htm")
    menu = form_menu(data)

    menu_res = {}
    chapter_count = sum(len(v) for v in menu.values())
    chapter_done = 0
    for key in menu.keys():
        res_list = []
        for idx, item in enumerate(menu[key]):
            chapter_done += 1
            title = item.text_content()
            print(f"[{chapter_done}/{chapter_count}] {key} - {title}")
            url_loc = f'{url_base}{item.get("href")}'
            chapter = get_content_with_images(idx, url_loc, title)
            res_list.append(chapter)
            time.sleep(crawl_delay)
        menu_res[key] = res_list

    toc = []
    img_list = []
    for key in menu_res.keys():
        section = epub.Section(key)
        section_list = [section, []]
        for item in menu_res[key]:
            if type(item) == ImagePage:
                for item2 in item.imagelist:
                    img_list.append(item2)
            section_list[1].append(item.xhtml)
        toc.append(section_list)

    book_title = data.xpath('string(//*[@id="title"])')
    book_author = data.xpath('string(//*[@id="info"])')[3:]
    book = book_init(book_title, book_author)
    book.toc = toc
    book.spine = ["cover", "nav"]
    for i in toc:
        for j in i[1]:
            book.add_item(j)
            book.spine.append(j)
    for i in img_list:
        book.add_item(i)
    book.add_item(epub.EpubNav())
    book.add_item(epub.EpubNcx())
    cover_file = fetch(url_cover)
    book.set_cover("cover.jpg", cover_file, create_page=False)

    safe_title = re.sub(r'[\\/:*?"<>|]', "_", book_title).strip() or "book"
    epub.write_epub(os.path.join(output_dir, f"{safe_title}.epub"), book)
