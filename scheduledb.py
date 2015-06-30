#!/usr/bin/env python2.7

import ConfigParser
import logging
from apscheduler.schedulers.background import BackgroundScheduler
import time
import datetime
import sys
import os
import shutil
import glob
import threading
import imp
import errno


def get_settings():
    configparser = ConfigParser.SafeConfigParser(os.environ)
    configparser.read("./settings.ini")
    settings = {
        'log_file': "default.log",
    }
    try:
        settings['plugindir'] = configparser.get('server', 'plugins_path')
        settings['links'] = configparser.get('server', 'db_links_path')
        settings['store'] = configparser.get('server', 'db_store_path')
    except:
        raise

    return settings


def update_status(statusdict, fname, fsched):
    # header
    fo = open(fname, 'w')
    fs = open(fsched, 'r')
    timestr = time.strftime("%d %b %Y %H:%M:%S", time.localtime())
    line = []
    line.append('BC2 Data    {}\n'.format(timestr))
    line.append('Live data directory: /import/bc2/data/test\n\n')
    line.append('{:<21s}{:<13s}{:<27s}{:<s}\n\n'.format(
        'Target', 'Status', 'Next check', 'Contact'))
    fo.write(''.join(line))
    # jobs
    firstline = True
    for job in fs:
        if firstline:
            firstline = False
            continue
        dbname = job.split()[0]
        contact = statusdict[dbname.split('-stable')[0]]['contact']
        email = statusdict[dbname.split('-stable')[0]]['email']
        nextupdate = ' '.join(job.split()[9:12])[:-1]
        if not dbname.split('-')[-1] == 'stable':
            status = statusdict[dbname]['status']
        else:
            status = 'up_to_date'
        line = '{:<21s}{:<13s}{:<27s}{:<s}\n'.format(
            dbname, status, nextupdate, contact + ' (' + email + ')')
        fo.write(line)
    fo.close()
    fs.close()
    return


def register_plugins(plugindir, settings):
    ''' registration of plugins and scheduling of jobs ''' 

    plugins = map(os.path.basename, glob.glob(os.path.join(plugindir, '*.py')))
    plugins = [p[:-3] for p in plugins]
   
    instance = {}
    for e in plugins:
        logger.info('Loading plugins: {}'.format(e))
        module = imp.load_source(e, os.path.join(plugindir, e + '.py'))
        instance[e] = module.create()
        #instance[e].__name__ = os.path.splitext(os.path.basename(module.__file__))[0]
        instance[e].init(e, store=settings['store'], links=settings['links'])

        # check start up state
        try:
            instance[e].initial_state_clean(settings)
        except:
           raise

        # register jobs (daily and stable)
        scheduler.add_job(
            instance[e].check, 'cron', args=[], name=e,
            day_of_week=instance[e].day_of_week, hour=instance[e].hour,
            day=instance[e].day, minute=instance[e].minute, second=instance[e].second)
        if instance[e].UPDATE_STABLE:
            scheduler.add_job(
                instance[e].check_update_stable, 'cron', args=[], name='{}-stable'.format(e),
                day_of_week=instance[e].stable_day_of_week, hour=instance[e].stable_hour,
                day=instance[e].stable_day, minute=instance[e].stable_minute, second=instance[e].stable_second)

    return instance


#######################################################################
# main
if __name__ == "__main__":

    # set up logging and scheduler
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    scheduler = BackgroundScheduler()

    # set up options
    plugindir = get_settings()['plugindir']
    store = get_settings()['store']
    links = get_settings()['links']

    try:
        # initialization. registration of plugins
        logger.info('Started')
        scheduler.start()
        plugins = register_plugins(plugindir, get_settings())

        while True:
            time.sleep(1)
            with open('schedulerjobs.log', 'w') as fo:
                scheduler.print_jobs(out=fo)
            status = {}
            for name, p in plugins.items():

                # there is a db to update
                if p.status == p.SGN_UPDATEME:
                    p.update_db()

                # finished downloading: rm directory, update symlinks
                if p.status == p.SGN_FINISHED:
                    p.update_links()

                # update stable if there is not daily update running
                if p.status_stable == p.SGN_UPDATEME:
                    p.update_db_stable()

                status[p.__name__] = dict(
                    status=p.status, contact=p.contact, email=p.email)

            update_status(status, 'status.log', 'schedulerjobs.log')

    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info('Cancelled')
