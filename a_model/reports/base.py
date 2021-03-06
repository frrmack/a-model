# NOTE: The quickbooks API is intended for webapps, not for people to download
# their own data. A simple downloading scheme with requests didn't work because
# of some janky ass javascript and iframe bullshit that quickbooks online has.
# Selenium was the best choice.
import os
import datetime
import glob
import time
import itertools
import json
import math
import re

import openpyxl
from selenium import webdriver
import gspread
from oauth2client.client import SignedJwtAssertionCredentials

from .. import utils

QUICKBOOKS_ROOT_URL = 'http://qbo.intuit.com'
EXCEL_MIMETYPES = (
    'application/vnd.ms-excel',
    'application/msexcel',
    'application/x-msexcel',
    'application/x-ms-excel',
    'application/x-excel',
    'application/x-dos_ms_excel',
    'application/xls',
    'application/x-xls',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
)


class Browser(webdriver.Firefox):
    """
    This class is a context manager to be sure to close the browser when we're
    all done.
    """
    def __init__(self, *args, **kwargs):

        # create a firefox profile to automatically download files (like excel
        # files) without having to approve of the download
        # http://bit.ly/1WeZziv
        profile = webdriver.FirefoxProfile()
        profile.set_preference("browser.download.folderList", 2)
        profile.set_preference(
            "browser.download.manager.showWhenStarting",
            False,
        )
        profile.set_preference("browser.download.dir", utils.DATA_ROOT)
        profile.set_preference(
            "browser.helperApps.neverAsk.saveToDisk",
            ','.join(EXCEL_MIMETYPES)
        )

        # instantiate a firefox instance and implicitly wait for find_element_*
        # methods for 10 seconds in case content does not immediately appear
        kwargs.update({'firefox_profile': profile})
        super(Browser, self).__init__(*args, **kwargs)
        self.implicitly_wait(30)

    # __enter__ and __exit__ make it a context manager
    # https://code.google.com/p/selenium/issues/detail?id=3228
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def login_quickbooks(self, username, password):
        self.get(QUICKBOOKS_ROOT_URL)
        self.find_element_by_name("login").send_keys(username)
        self.find_element_by_name("password").send_keys(password)
        self.find_element_by_id("LoginButton").click()


class Report(object):
    report_name = None
    gsheet_tab_name = None

    # parameters for quickbooks url
    # url for quickbooks QUICKBOOKS_ROOT_URL
    start_date = datetime.date(2014, 1, 1)
    end_date = utils.end_of_last_month()

    def __init__(self):
        self.filename = os.path.join(
            utils.DATA_ROOT, self.report_name
        )

    def get_date_customized_params(self):
        return (
            ('high_date', utils.qbo_date_str(self.end_date)),
            ('low_date', utils.qbo_date_str(self.start_date)),
            ('date_macro', 'custom'),
            ('customized', 'yes'),
        )

    def get_qbo_query_params(self):
        raise NotImplementedError

    @property
    def url(self):
        """convenience function for creating report urls"""
        report_url = QUICKBOOKS_ROOT_URL + '/app/report'
        return report_url + '?' + utils.urlencode(self.get_qbo_query_params())

    def download_from_quickbooks(self, browser):
        # remove all of the old report*.xlsx crappy filenames that quickbooks
        # creates by default
        report_regex = os.path.join(utils.DATA_ROOT, 'report*.xlsx')
        for filename in glob.glob(report_regex):
            os.remove(filename)

        # go to the P&L page and download the report locally
        browser.get(self.url)
        iframe = browser.find_element_by_tag_name('iframe')
        browser.switch_to_frame(iframe)
        iframe2 = browser.find_element_by_tag_name('iframe')
        browser.switch_to_frame(iframe2)
        browser.find_element_by_css_selector('option[value=xlsx]').click()
        browser.switch_to_default_content()

        # check to see if the file has been downloaded
        while not glob.glob(report_regex):
            time.sleep(1)
        qbo_filename = glob.glob(report_regex)[0]
        os.rename(qbo_filename, self.filename)

    def open_google_workbook(self):
        """Convenience method for opening up the google workbook"""

        # read json from file
        gdrive_credentials = os.path.join(utils.DROPBOX_ROOT, 'gdrive.json')
        with open(gdrive_credentials) as stream:
            key = json.load(stream)

        # authorize with credentials
        credentials = SignedJwtAssertionCredentials(
            key['client_email'],
            key['private_key'],
            ['https://spreadsheets.google.com/feeds'],
        )
        gdrive = gspread.authorize(credentials)

        # open spreadsheet and read all content as a list of lists
        return gdrive.open_by_url(key['url'])

    def open_google_worksheet(self):
        google_workbook = self.open_google_workbook()
        return google_workbook.worksheet(self.gsheet_tab_name)

    def download_from_gdrive(self):
        google_worksheet = self.open_google_worksheet()
        response = google_worksheet.export('xlsx')
        with open(self.filename, 'w') as output:
            output.write(response.read())
        print self.filename

    def upload_to_gdrive(self):
        # parse the resulting data from xlsx and upload it to a google
        # spreadsheet
        excel_worksheet = self.open_worksheet()
        pl_dimension = excel_worksheet.calculate_dimension()
        excel_row_list = excel_worksheet.range(pl_dimension)
        excel_cell_list = itertools.chain(*excel_row_list)

        # clear the google doc contents
        google_worksheet = self.open_google_worksheet()
        print google_worksheet.row_count, google_worksheet.col_count
        not_empty_cells = google_worksheet.findall(re.compile(r'[a-zA-Z0-9]+'))
        for cell in not_empty_cells:
            cell.value = ''
        google_worksheet.update_cells(not_empty_cells)

        # upload the contents
        google_cell_list = google_worksheet.range(pl_dimension)
        for google_cell, excel_cell in zip(google_cell_list, excel_cell_list):
            if excel_cell.value is None:
                google_cell.value = ''
            else:
                google_cell.value = excel_cell.value
        google_worksheet.update_cells(google_cell_list)

    def open_worksheet(self):
        # all of the quickbooks reports only have one active sheet
        workbook = openpyxl.load_workbook(self.filename)
        self.worksheet = workbook.active
        return self.worksheet

    def _row_cell_range(self, row, min_col, max_col):
        return '%(min_col)s%(row)d:%(max_col)s%(row)d' % locals()

    def _col_cell_range(self, col, min_row, max_row):
        return '%(col)s%(min_row)d:%(col)s%(max_row)d' % locals()

    def iter_cells_in_range(self, cell_range):
        for row in self.worksheet.iter_rows(cell_range):
            for cell in row:
                yield cell

    def iter_cells_in_row(self, row, min_col, max_col):
        cell_range = self._row_cell_range(row, min_col, max_col)
        return self.iter_cells_in_range(cell_range)

    def iter_cells_in_column(self, col, min_row, max_row):
        cell_range = self._col_cell_range(col, min_row, max_row)
        return self.iter_cells_in_range(cell_range)

    def get_date_from_cell(self, date_cell):
        if isinstance(date_cell.value, datetime.datetime):
            date = date_cell.value
        else:
            try:
                date = datetime.datetime.strptime(date_cell.value, '%b %Y')
            except ValueError:
                date = utils.qbo_date(date_cell.value)
        return utils.end_of_month(date)

    def get_now(self):
        return utils.end_of_last_month()

    def get_months_from_now(self, date):
        now = self.get_now()
        delta = date - now
        return int(math.floor(delta.days / 30.))

    def get_date_in_n_months(self, n_months):
        t = self.get_now()
        for month in range(n_months):
            t += datetime.timedelta(days=1)
            t = utils.end_of_month(t)
        return t

    def get_float_from_cell(self, float_cell):
        if float_cell.value is None:
            return 0.0
        elif isinstance(float_cell.value, (float, int)):
            return float(float_cell.value)
        else:
            return float(float_cell.value.strip('='))

    def cache_report_locally(self):
        raise NotImplementedError
