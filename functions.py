"""
The functions of the new crawler projects
"""
import re
import os
import pandas as pd
import time
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests as res
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util import Retry
from ebooklib import epub

common_headers = {
    'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.61 Safari/537.36 Edg/94.0.992.31"
    }

html_name_match = re.compile('([0-9]+).(htm)')
img_name_match = re.compile('[0-9]+.(jpg|png|jpeg)')


class ContentPage:
    """
    A class represents every pages on the novel menu.
    """

    def __init__(self, href, title, idx, content):
        self.xhtml = epub.EpubHtml(
            title=title, file_name=href, media_type='xhtml', content=content)
        self.idx = idx


class ImagePage(ContentPage):
    """
    A class represents pages containing images.
    """

    def __init__(self, href, title, idx, content, imagelist):
        super().__init__(href, title, idx, content)
        self.imagelist = imagelist

def BookTitleList(max_number=0):
    if not os.path.exists("book_title_list.db"):
        con = sqlite3.connect("book_title_list.db")
        cur = con.cursor()
        cur.execute("""CREATE TABLE book
            (id INTEGER PRIMARY KEY, 
             title TEXT, 
             author TEXT,
             status BOOLEAN);""")
        con.commit()
        start_number = 1
    else:
        con = sqlite3.connect("book_title_list.db")
        cur = con.cursor()
        start_number = cur.execute('SELECT max(id) FROM book').fetchone()[0]+1
    
    res = []
    for i in range(start_number, start_number+max_number):
        url_base = 'https://www.wenku8.net/novel/{}/{}/'.format(i//1000, i)+'{}'
        url = url_base.format('index.htm')
        data = GetData(url)
        try:
            title = data.find(id='title').get_text()
        except:
            continue
        author = data.find(id='info').get_text()[3:]
        try:
            check = data.find_all(class_='ccss')[0]
        except:
            print(f"{title} no content.")
            continue
        check_href = check.contents[0].get('href')
        check_data = GetData(url_base.format(check_href))
        if '因版权问题，文库不再提供该小说的阅读！' in check_data.find(id='content').contents:
            status = 0
        else:
            status = 1
        res.append([i, title, author, status])
        print([i, title, author, status])

        time.sleep(1)
    
    cur.executemany("INSERT INTO book VALUES(?,?,?,?)", res)
    con.commit()
    con.close()
    
    return start_number+max_number-1


def Get(url: str, headers=common_headers):
    s = res.Session()
    s.mount('https://', HTTPAdapter(max_retries=Retry(total=5)))
    resp_get = s.get(url=url, headers=headers, timeout=(2,10))
    return resp_get.content


def GetData(url: str, headers=common_headers):
    s = res.Session()
    s.mount('https://', HTTPAdapter(max_retries=Retry(total=5)))
    resp_get = s.get(url=url, headers=headers, timeout=(2,10))
    data = BeautifulSoup(resp_get.content, features='html.parser')
    return data


def FormMenu(data: BeautifulSoup) -> dict:
    """
    Use the list of volumes and chapters to form the menu list
    :param data: list of volumes and chapters
    :return: list
    """
    data = data.find_all(class_=['vcss', 'ccss'])
    res = dict()
    idx = None
    for item in data:
        if item.get('class') == ['vcss']:
            idx = item.get_text()
            res[idx] = []
        elif item.get('class') == ['ccss']:
            if idx == None:
                print(res)
                raise ValueError(
                    "The first item of the list is not the volume")
            if item.get_text() != '\xa0':
                res[idx].append(item.contents[0])
    return res


def GetContent(idx: int, url: str, title: str):
    data = GetData(url)
    data = str(data.find(id='content'))
    data = data.replace('\xa0\xa0\xa0\xa0', '\xa0\xa0')
    data = data.replace('\xa0\xa0\xa0', '\xa0\xa0')
    data = data[78:len(data)-6]
    return ContentPage(html_name_match.search(url).group(1)+'.xhtml', title, idx, data)


def GetSinglePicture(idx: int, url: str, title: str):
    data = Get(url)
    pic = epub.EpubImage()
    pic.file_name = title
    pic.media_type = 'image/'+img_name_match.match(title).group(1)
    pic.content = data
    return (idx, pic)


def GetPictures(idx0: int, url: str, title: str):
    href = html_name_match.search(url).group()
    data = GetData(url)
    data = data.find_all(class_='imagecontent')
    data = list(map(lambda x: x.get('src'), data))
    lens = len(data)
    res = [0] * lens

    content = "\n<br>\n".join(list(
        map(lambda x: '<img src="{}">'.format(img_name_match.search(x).group()), data)))

    with ThreadPoolExecutor(max_workers=lens) as t:
        obj_list = []
        for idx, item in enumerate(data):
            img_title = img_name_match.search(item).group()
            obj = t.submit(GetSinglePicture, idx, item, img_title)
            obj_list.append(obj)

        for future in as_completed(obj_list):
            res_tmp = future.result()
            res[res_tmp[0]] = res_tmp[1]

    result = ImagePage(href, title, idx0, content, res)

    return result


def book_init(title: str, author: str):
    book = epub.EpubBook()
    book.set_identifier('BlueRain77')
    book.set_title(title)
    book.add_author(author)
    book.set_language('zh')

    return book


def get_ebook(id: int, headers=common_headers):
    """
    Main function of getting ebook.
    """
    url_base = 'https://www.wenku8.net/novel/{}/{}/'.format(id//1000, id)+'{}'
    url_cover = "https://img.wenku8.com/image/{}/{}/{}s.jpg".format(id//1000, id, id)

    data = GetData(url_base.format('index.htm'))

    menu = FormMenu(data)

    menu_res = {}
    for key in menu.keys():
        lens = len(menu[key])
        res_list = [0]*lens
        with ThreadPoolExecutor(max_workers=lens) as t:
            obj_list = []
            for idx, item in enumerate(menu[key]):
                url_loc = url_base.format(item.get('href'))
                if item.get_text() == '插图':
                    obj = t.submit(GetPictures, idx, url_loc, item.get_text())
                else:
                    obj = t.submit(GetContent, idx, url_loc, item.get_text())
                obj_list.append(obj)

            for future in as_completed(obj_list):
                res = future.result()
                res_list[res.idx] = res

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

    book = book_init(data.find(id='title').get_text(),
                     data.find(id='info').get_text()[3:])
    book.toc = toc
    book.spine = ['cover','nav']
    for i in toc:
        for j in i[1]:
            book.add_item(j)
            book.spine.append(j)
    for i in img_list:
        book.add_item(i)
    book.add_item(epub.EpubNav())
    book.add_item(epub.EpubNcx())
    cover_file = Get(url_cover)
    book.set_cover('cover.jpg', cover_file, create_page=False)

    epub.write_epub(data.find(id='title').get_text()+'.epub', book)
