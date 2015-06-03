#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys, os, time, thread, glib, gobject, re
import pickle, ConfigParser
import pygst
pygst.require("0.10")
import gst, json, urllib, urllib2, httplib, contextlib, random, binascii
from select import select
from Cookie import SimpleCookie
from contextlib import closing
import douban
import datetime

class DoubanFM_CLI:
    def __init__(self):
        config = ConfigParser.SafeConfigParser({
            'interval': '0',
            'pre_set_channel': 'False',
            'pre_set_channel_id': '0'})
        config.read('doubanfm.config')
        self.delay_after_every_song = config.getfloat('DEFAULT', 'interval')

        if config.getboolean('DEFAULT', 'pre_set_channel'):
            self.channel = str(config.getint('DEFAULT', 'pre_set_channel_id'))
        else:
            Channel().show()
            self.channel = raw_input('请输入您想听的频道数字:')

        self.skip_mode = False
        self.user = None
        self.username = ''
        self.player = gst.element_factory_make("playbin", "player")
        self.pause = False
        self.playing = False
        bus = self.player.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)
        self.ch = 'http://douban.fm/j/mine/playlist?type=p&sid=&channel='+self.channel

    def on_message(self, bus, message):
        t = message.type
        if t == gst.MESSAGE_EOS:
            self.player.set_state(gst.STATE_NULL)
            self.playmode = False
        elif t == gst.MESSAGE_BUFFERING:
            percent = message.parse_buffering()
            sys.stdout.write(u"\r缓冲进度: %d%%... " % percent)
            sys.stdout.flush()
        elif t == gst.MESSAGE_ERROR:
            self.player.set_state(gst.STATE_NULL)
            err, debug = message.parse_error()
            print "Error: %s" % err, debug
            self.playmode = False
        elif t== gst.MESSAGE_STATE_CHANGED: 
            old_state, new_state, pending_state = message.parse_state_changed()
            if new_state == gst.STATE_PLAYING:
                self.playing = True
            elif new_state == gst.STATE_PAUSED:
                self.playing = False

    def get_songlist(self):
        if self.channel == '0' or self.channel == '-3':
            self.private = True
        else:
            self.private = False

        if self.private:
            self.user = douban.PrivateFM(self.channel)
            self.songlist = self.user.playlist()
        else:
            self.songlist = json.loads(urllib.urlopen(self.ch).read())['song']

    def control(self,r):
        rlist, _, _ = select([sys.stdin], [], [], 1)
        if rlist:
            s = sys.stdin.readline().rstrip()
            if s:
                if s == 'n':
                    print '下一首...'
                    self.skip_mode = True
                    return 'next'
                elif s == 'f' and self.private:
                    print '正在加心...'
                    self.user.fav_song(r['sid'], r['aid'])
                    print "加心成功:)\n"
                    return 'fav'
                elif s == 'd' and self.private:
                    print '不再收听...'
                    self.songlist = self.user.del_song(r['sid'], r['aid'])
                    print "删歌成功:)\n"
                    return 'del'
                elif s == 'p' and not self.pause:
                    print '已暂停...'
                    print '输入r以恢复播放\n'
                    return 'pause'
                elif s == 'r' and self.pause:
                    print '恢复播放...'
                    print '继续享受美妙的音乐吧:)\n'
                    return 'resume'
                elif s == 'c' :
                    Channel().show()
                    print('请输入您想听的频道数字:')
                elif s == 'h' :
                    self.print_menu() 
                elif s.isdigit() or (s.startswith('-') and s[1:].isdigit()):
                    self.channel = s
                    return 'channel'
                else:
                    print '错误的操作，请重试\n'

    def print_menu(self):
        print u"\r\n\t跳过输入n，加心输入f，删歌输入d，暂停输入p，播放输入r，切换频道输入c\r\n"


    def start(self, loop):
        print u'\n正在播放 %s 频道\n' % Channel().info[int(self.channel)]
        self.get_songlist()
        is_first_song = True
        for r in self.songlist:
            song_uri = r['url']
            self.playmode = True
            self.pause = False

            if not is_first_song and not self.skip_mode:
                if self.delay_after_every_song > 0:
                    print '-'
                    time.sleep(self.delay_after_every_song)
            self.skip_mode = False
            is_first_song = False

            print u'\n\n正在播放： '+r['title']+u'     歌手： '+r['artist'],
            if int(r['like']) == 1:
                print u'    ♥\n'
            else:
                print '\n'

            self.player.set_property("uri", song_uri) # when ads, flv, warning print
            self.player.set_state(gst.STATE_PLAYING)
            while self.playmode:
                c = self.control(r)
                if c == 'next' or c == 'del':
                    self.player.set_state(gst.STATE_NULL)
                    self.playmode = False
                    break
                elif c == 'pause':
                    self.pause = True
                    self.player.set_state(gst.STATE_PAUSED)
                elif c == 'resume':
                    self.pause = False
                    self.player.set_state(gst.STATE_PLAYING)
                elif c == 'channel':
                    self.player.set_state(gst.STATE_NULL)
                    self.playmode = False
                    break
                elif self.playing == True and self.playmode == True:
                    try:
                        duration = self.player.query_duration(gst.FORMAT_TIME)
                        position = self.player.query_position(gst.FORMAT_TIME)
                    except Exception, e:
                        pass
                    else:
                        dura = datetime.timedelta(seconds=(duration[0] / gst.SECOND))
                        posi  = datetime.timedelta(seconds=(position[0] / gst.SECOND))
                        progress = str(posi)[2:]+" / " +str(dura)[2:]
                        sys.stdout.write(u"\r%s%s        " % ("  ",progress))
                        sys.stdout.flush()
            if c == 'channel':
                break 

        loop.quit()


class Channel:

    def __init__(self):
        cid = "101" # why cid is 101 ?
        self.url = "http://douban.fm/j/explore/channel_detail?channel_id=" + cid
        self.init_info()

    def init_info(self):
        cache = douban.Cache()
        if cache.has('channel'):
            self.info = cache.get('channel')
        else:
            self.info = {
                    0: u"私人",
                    -3: u"红心"
                }
            self.get_id_and_name()
            cache.set('channel', self.info)

    def get_id_and_name(self):
        print '获取频道列表…\n'
        # this var should name to text or string or something
        self.html = urllib2.urlopen(self.url).read()
        chls = json.loads(self.html)["data"]["channel"]["creator"]["chls"]
        for chl in chls:
            id = chl["id"]
            name = chl["name"]
            self.info[id] = name

    def show(self):
        print u'频道列表：'
        for i in sorted(self.info.iterkeys()):
            print("%8s %s" % (i, self.info[i]))

def main():
    print u'豆瓣电台'
    doubanfm = DoubanFM_CLI()

    doubanfm.print_menu()

    while 1:
        loop = glib.MainLoop()
        thread.start_new_thread(doubanfm.start, (loop,))
        gobject.threads_init()
        loop.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print "再见！"
