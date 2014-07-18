#!/usr/bin/env python
import os
import re
import sys
import argparse
from subprocess import Popen,PIPE,getoutput,check_call,CalledProcessError
import logging

ver='1.6'

'''
v1.1  2011-7-19
a./startagent.sh and /stopagent.sh missed quote mark at the end of each line
b.modify auto start script /etc/rc.itm .copy from /startagent.sh

v1.2  2011-08-04
a.change method chg_permission from setperm to secureMain 

v1.3  2012-7-18
a. change itmcmd config for UD( runitmcmd method ) ,use -o option to set instance name

v1.4  2012-8-1
a. add second connect ip parameter -sectms

v1.5 2014-3-24
a. add pre and post script check and fix action

v1.6 2014-05-22
a. remove prescript and postscript dependency (create instance first)
'''


hostname = os.uname()[1]

logger = logging.getLogger('itmcfg')
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler('itmcfg.log')
fh.setLevel(logging.DEBUG)

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)

fh_fmter = logging.Formatter('%(asctime)s|%(funcName)-12s %(lineno)-4d: %(levelname)-8s %(message)s')
ch_fmter = logging.Formatter('%(levelname)-8s %(message)s')

fh.setFormatter(fh_fmter)
ch.setFormatter(ch_fmter)

logger.addHandler(fh)
logger.addHandler(ch)



def ipaddress(string):
    value = str(string)
    result = re.match('^([01]?\d\d?|2[0-4]\d|25[0-5])\.([01]?\d\d?|2[0-4]\d|25[0-5])\.([01]?\d\d?|2[0-4]\d|25[0-5])\.([01]?\d\d?|2[0-4]\d|25[0-5])$',value)
    if not result:
        msg = '{0} is not a valid ip address'.format(value)
        raise argparse.ArgumentTypeError(msg)
    return value
    
def itmarg_par():
    parser = argparse.ArgumentParser(
        prog = 'itmcfg',
        description='Example:itmcfg -prescript /opt/itm6/bcitmcfg/prescript.sh -rtms 182.248.56.61 -secrtms 182.248.56.60 -pclist ux ul um px mq ud -isha Yes -qmgr q1 q2 -inst db2inst1 db2inst2 -postscript /opt/itm6/bcitmcfg/postscript.sh',
        epilog='BOCOM DC ITM6 Manual Configuration Script.. Author:linhaolh@cn.ibm.com')
                                        
    parser.add_argument('-prescript',help='pre scripts such as checking and fix action')
    parser.add_argument('-postscript',help='post scripts such as checking and fix action')
    parser.add_argument('-rtms',required=True,type=ipaddress,help='ip address for first remote tems')
    parser.add_argument('-secrtms',required=True,type=ipaddress,help='ip address for second remote tems')
    parser.add_argument('-pclist',nargs='+',required=True,metavar='pc',help='production codes like ux,ul,um')
    parser.add_argument('-isha',required=True,choices={'Yes','No'},help='wheter this OS running on HACMP or Not')
    parser.add_argument('-ch',nargs='?',const='/opt/itm6',default='/opt/itm6',metavar='CANDLEHOME',help='candle home')
    parser.add_argument('-version', action='version', version='%(prog)s ' + ver)
    parser.add_argument('-qmgr',nargs='*',metavar='qmgrN',help='mq qmgr name')
    parser.add_argument('-inst',nargs='*',metavar='instN',help='db2 instance name')
    
    return parser.parse_args()
    #print(args)
     
class UsageExc(Exception):
    mydic = dict(mq='-qmgr',ud='-inst')
    def __init__(self,pc):
        self.pc = pc
        msg = 'pc list include item:({0}),please use argument:({1})'.format(self.pc,self.mydic[self.pc])
        print('-'*len(msg))
        print(msg)
        print('-'*len(msg))
        parser.print_usage()                
    def __str__(self):
        return 'Error argument!!!' 



class TemaCfg:
    strscripts = os.path.join('/','startagent.sh')
    stpscripts = os.path.join('/','stopagent.sh')
    

    def __init__(self,args,hostname=None):
        self.rtms = args.rtms
        self.secrtms = args.secrtms
        self.pclist=args.pclist
        self.isha=args.isha
        self.candlehome=args.ch
        self.qmgr=args.qmgr
        self.inst=args.inst
        self.prescript=args.prescript
        self.postscript=args.postscript
        self.hostname=hostname

        autostr = os.path.join(self.candlehome,'registry','AutoStart')
        with open(autostr) as myfile:
            filenum = myfile.read().strip()
        self.rcitmx = '/etc/rc.itm' + filenum
                  
    def modify_ini(self):
        logger.info('starting modify pc.ini...')
        for pc in self.pclist:
            logger.info('start processing {0}.ini ...'.format(pc))
            ininame = pc + '.ini'
            inifile = os.path.join(self.candlehome,'config',ininame)
            self.cfg_ini_bak(inifile)
            append_list=['CTIRA_HOSTNAME=' + self.hostname + '\n',
                         'CTIRA_SYSTEM_NAME=' + self.hostname + '\n'
                         ]
            if pc == 'ux':
                append_list+=['CTIRA_HEARTBEAT=5\n']  ###add heartbeat for ux.ini
            pat1 = re.compile(r'^CTIRA_HOSTNAME=')
            pat2 = re.compile(r'^CTIRA_SYSTEM_NAME=')
            pat3 = re.compile(r'^CTIRA_HEARTBEAT=')
            
            with open(inifile) as myfile:
                ini_list = myfile.readlines()
            del_list = [line for line in ini_list if pat1.match(line) or pat2.match(line) or pat3.match(line)]
                         
            for line in del_list: 
                ini_list.remove(line)
            
            final_list=ini_list + append_list
            with open(inifile,'w') as myfile:
                myfile.writelines(final_list)
                logger.info('ended process {0}.ini ...'.format(pc))
            if pc == 'mq': self.modify_mq_cfg()  ###add "SET AGENTNAME" for mq.cfg
        logger.info('ended modify pc.ini')

    def modify_mq_cfg(self):
        logger.info('starting modify mq.cfg...')
        mqcfg_file= os.path.join(self.candlehome,'config','mq.cfg')
        self.cfg_ini_bak(mqcfg_file)
        additem = 'SET AGENT NAME(' + self.hostname + ')' + '\n'
        with open(mqcfg_file) as myfile:
            mqcfg = myfile.readlines()
        pat1 = re.compile(r'^SET MANAGER NAME')
        pat2 = re.compile(r'^SET AGENT NAME')

        del_list = [ x for x in mqcfg if pat2.match(x) ]
        for line in del_list:
            mqcfg.remove(line)

        for i in range(len(mqcfg)):
            if pat1.match(mqcfg[i]):
                mqcfg.insert(i+1,additem)
        with open(mqcfg_file,'w') as myfile:
            myfile.writelines(mqcfg)
       
        logger.info('ended modify mq.cfg')

         
    def run_itmcmd(self):
        logger.info('starting run itmcmd silent config command...') 
        file_silentcfg=os.path.join(self.candlehome,'silent_config.txt')
        silent_cfg_tup = ('HOSTNAME=' + self.rtms,
                      'FTO=YES',
                      'MIRROR=' + self.secrtms,
                      'HSNETWORKPROTOCOL=ip.pipe'
                     ) 
        silent_cfg='\n'.join(silent_cfg_tup)
        logger.info('slient config file content')
        logger.info('\n' + silent_cfg)
        with open(file_silentcfg,'w') as myfile:
            myfile.write(silent_cfg)
        for pc in self.pclist: 
            logger.info('starting slient config {0}'.format(pc))

            if pc == 'ud':
                for inst in self.inst:
                    ret=Popen(['/opt/itm6/bin/itmcmd','config','-A','-h',self.candlehome,'-o',inst,'-p',file_silentcfg,pc],stdout=PIPE,stderr=PIPE)
                    boutput=ret.communicate()[0]
                    output=str(boutput,encoding='utf-8')
                    logger.info('\n' + output)
            else:
                ret=Popen(['/opt/itm6/bin/itmcmd','config','-A','-h',self.candlehome,'-p',file_silentcfg,pc],stdout=PIPE,stderr=PIPE)
                boutput=ret.communicate()[0]
                output=str(boutput,encoding='utf-8')
                logger.info('\n' + output)
        
        logger.info('ended run itmcmd silent config command') 
    
    def modify_kulconfig(self):
        if 'ul' in self.pclist:
            logger.info('starting modify kul_configfile for ulagent...')
            kul_cfgfile = os.path.join(self.candlehome,'config','kul_configfile')
            self.cfg_ini_bak(kul_cfgfile)
            pat1=re.compile(r'^#/var/adm/ras/errlog')
            pat2=re.compile(r'^/var/hacmp')
            with open(kul_cfgfile) as myfile:
                kul_cfgfile_list = myfile.readlines()
            for i in range(len(kul_cfgfile_list)):
                if pat1.match(kul_cfgfile_list[i]):
                    cfgerrpt=kul_cfgfile_list.pop(i)[1:]
                    kul_cfgfile_list.insert(i,cfgerrpt)
            if self.isha == 'Yes':
                del_item = [ x for x in kul_cfgfile_list if pat2.match(x) ]
                for x in del_item:
                    kul_cfgfile_list.remove(x)  
                clcfg = [
                          '/var/hacmp/adm/cluster.log',
                           ';n',
                           ';u',
                           ';a,"%s %d %d:%d:%d %s %s %[^:]: %[^:]: %[^\\n]" , month day hour minute second system type source class description']
                clcfg = '\t'.join(clcfg)
                kul_cfgfile_list.append(clcfg + '\n')

            with open(kul_cfgfile,'w') as myfile:
                myfile.writelines(kul_cfgfile_list)
            logger.info('ended modify kul_configfile for ulagent')

        
    def modify_inttab(self):
        initab = '/etc/inittab' 
        if self.isha == 'Yes':
            logger.info('This OS running on HACMP, delete autostart item from /etc/inittab')
            self.cfg_ini_bak(initab) 
            ret=Popen(['/etc/lsitab','-a'], stdout=PIPE, stderr=PIPE)
            b_iden=ret.stdout.readlines()
            iden = list(map(lambda x: str(x,encoding='utf-8'), b_iden))
            iden_del= [x.split(':')[0] for x in iden if re.match('rcitm',x)]
            try:
                for x in iden_del:
                   check_call(['/etc/rmitab', x])
            except CalledProcessError as E:
                logger.error('system command [{0}] return non-zero [{1}] code'.format(E.cmd,E.returncode))

            logger.info('Auto start items (' + ','.join(iden_del) + ') has deleted!!')           

        

    def modify_startagent(self):
        logger.info('starting modify manually start script /startagent.sh...')
        startcont = ['#!/bin/ksh', 
                     'start_all()',
                     '{',
                     '}',
                     '#'*10,
                     'if [ -f /opt/itm6/bin/CandleAgent ]',
                     'then',
                     '  start_all',
                     'fi\n'
                     ]
        single_item = ['/usr/bin/su',
                       '-',
                       'itm6',
                       '-c',
                       '"',
                       '/opt/itm6/bin/itmcmd',
                       'agent',
                       'start',
                       'pc',
                       '>/dev/null',
                       '2>&1',
                       '"'
                       ]
        all_item=[]
        for pc in self.pclist:
            logger.debug('processing(' + pc + ') start item...')
            all_item+=self.singel_pc_start(pc,single_item)
            logger.debug('ended process(' + pc + ')start item')

        for item in all_item:
            startcont.insert(-6,item)

        with open(self.strscripts,'w') as myfile:
            myfile.write('\n'.join(startcont))

        logger.info('ended modify manually start script /startagent.sh')

    def modify_stopagent(self):
        logger.info('starting modify manually stop script /stopagent.sh....')
        start= open(self.strscripts)
        stop=open(self.stpscripts,'w')
        stop.write(start.read().replace('start','stop'))
        start.close()
        stop.close()
        logger.info('ended modify manually stop script /stopagent.sh')

    def modify_autostr(self): ###run after /startagent.sh has been creaed
        if self.isha == 'No':
            logger.info('starting modify autostart scripts /etc/rc.itm...')
            self.cfg_ini_bak(self.rcitmx) 
            try:
                check_call(['cp',self.strscripts,self.rcitmx])
            except CalledProcessError as E:
                logger.error('system command [{0}] return non-zero [{1}] code'.format(E.cmd,E.returncode))
            logger.info('ended modify autostart scripts /etc/rc.itm...')

    def singel_pc_start(self,pc,template):
        if pc in ['ux','ul','um','px']:
            retl = []
            temp = template[:]
            temp.pop(-4)
            temp.insert(-3,pc)
            retl.append(' '.join(temp))
            return retl
        elif pc == 'mq':
            mqitem=[]
            for qmgr in self.qmgr:
                temp = template[:]
                temp.pop(-4)
                temp.insert(-3,'mq')
                for x in ['-o',qmgr]:
                    temp.insert(-5,x)
                mqitem.append(' '.join(temp))
            return mqitem
        elif pc == 'ud':
            uditem=[]
            for inst in self.inst:
                temp = template[:]
                temp.pop(2)
                temp.insert(2,inst)
                temp.pop(-4)
                temp.insert(-3,'ud')
                for x in ['-o',inst]:
                    temp.insert(-5,x)
                uditem.append(' '.join(temp))
            return uditem



    def cfg_ini_bak(self,ininame):
        bak_orig = ininame + '.orig'
        try:
            check_call(['cp','-p',ininame,bak_orig])
        except CalledProcessError as E:
            logger.error('system command [{0}] return non-zero [{1}] code'.format(E.cmd,E.returncode))
        
    def chg_user_group(self):
        if self.qmgr:
            logger.info('starting add user account (itm6) into group (mqm)...')
            try:
                check_call(['chgrpmem','-m','+','itm6','mqm'])
            except CalledProcessError as E:
                logger.error('system command [{0}] return non-zero [{1}] code'.format(E.cmd,E.returncode))
            logger.info('ended add user account (itm6) into group (mqm)')
        if self.inst:
            for inst in self.inst:
                logger.info('starting add db2 inst user (' + inst + ') account into group (itmusers)...')
                try:
                    check_call(['chgrpmem','-m','+',inst,'itmusers'])
                except CalledProcessError as E:
                    logger.error('system command [{0}] return non-zero [{1}] code'.format(E.cmd,E.returncode))
                logger.info('ended add db2 inst user (' + inst + ') account into group (itmusers)...')


    def chg_permission(self):
        logger.info('starting modify related files and directories permission...') 
        #setperm = os.path.join(self.candlehome,'bin','SetPerm')
        secureMain = os.path.join(self.candlehome,'bin','secureMain')
        try:
            logger.info('change /startagent.sh and /stopagent.sh owner to itm6:itmusers')
            check_call(['chown','itm6:itmusers',self.strscripts,self.stpscripts])
            logger.info('change /startagent.sh and /stopagent.sh permissoin mode to 744')
            check_call(['chmod','744',self.strscripts,self.stpscripts])
            logger.info('change whole /opt/itm6 directory owner to itm6:itmusers')
            check_call(['chown','-R','itm6:itmusers',self.candlehome])
            #logger.info('change whole /opt/itm6 directory permission modeto o-rwx')
            #check_call(['chmod','-R','o-rwx',self.candlehome])
            #logger.info('run /opt/itm6/bin/SerPerm to set suid bit for itm6 binaries')
            #check_call([setperm,'-a','-h',self.candlehome])
            logger.info('run /opt/itm6/bin/secureMain lock to set necessary permission')
            check_call([secureMain,'-h',self.candlehome,'-g','itmusers','lock'])
        except CalledProcessError as E:
            logger.error('system command [{0}] return non-zero [{1}] code'.format(E.cmd,E.returncode))
        logger.info('ended modify related files and directories permission...') 


    def chk_output(self):
        logger.info('-'*30 + 'OUTPUT RESULT' + '-'*30)
        for pc in self.pclist:
            ininame = pc + '.ini'
            logger.info('-'*20 + ininame + '-'*20)
            cmd = 'cat /opt/itm6/config/' + ininame + ' | grep -E "CTIRA_HOSTNAME|CTIRA_SYSTEM_NAME"'
            output = getoutput(cmd)
            logger.info('\n' + output)
            logger.info('-'*20 + ininame + '-'*20)
            if pc == 'mq':
                logger.info('-'*20 + 'mq.cfg' + '-'*20)
                cmd = 'cat /opt/itm6/config/mq.cfg | grep "SET AGENT NAME"'
                output = getoutput(cmd)
                logger.info('\n' + output)
                logger.info('-'*20 + 'mq.cfg' + '-'*20)
        if 'ul' in self.pclist:
            logger.info('-'*20 + 'kul_configfile' + '-'*20)
            cmd = "cat /opt/itm6/config/kul_configfile | grep -v '^#' | grep -v '^$' "
            output = getoutput(cmd)
            logger.info('\n' + output)

        logger.info('-'*20 + '/etc/inittab' + '-'*20)
        cmd = 'cat /etc/inittab | grep rcitm'
        output = getoutput(cmd)
        logger.info('\n' + output)

        
        logger.info('-'*20 + '/startagent.sh' + '-'*20)
        cmd = 'cat /startagent.sh'
        output = getoutput(cmd)
        logger.info('\n' + output)

        logger.info('-'*20 + '/stopagent.sh' + '-'*20)
        cmd = 'cat /stopagent.sh'
        output = getoutput(cmd)
        logger.info('\n' + output)

        logger.info('-'*20 + self.rcitmx + '-'*20)
        cmd = 'cat ' + self.rcitmx
        output = getoutput(cmd)
        logger.info('\n' + output)

        if self.qmgr:
            logger.info('-'*20 + 'mqm group info' + '-'*20)
            cmd = 'cat /etc/group | grep mqm'
            output = getoutput(cmd)
            logger.info('\n' + output)
        if self.inst:
            logger.info('-'*20 + 'itmusers group info' + '-'*20)
            cmd = 'cat /etc/group | grep itmusers'
            output = getoutput(cmd)
            logger.info('\n' + output)
        
        logger.info('-'*20 + 'permission for /startagent.sh and /stopagent.sh' + '-'*20)
        cmd = 'ls -l /startagent.sh /stopagent.sh'
        output = getoutput(cmd)
        logger.info('\n' + output)

        logger.info('-'*20 + 'permission for /opt/itm6 directory' + '-'*20)
        cmd = 'ls -ld /opt/itm6'
        output = getoutput(cmd)
        logger.info('\n' + output)
        
        for pc in self.pclist:
            logger.info('-'*20 + 'SetPerm result for ' + pc + '-'*20)
            pattern = pc + '/bin'
            kpc = 'k' + pc + '*'
            for dirpath, dirnames, filenames in os.walk(self.candlehome):
                if dirpath[-6:] == pattern:
                    cmd = 'ls -l ' + os.path.join(dirpath, kpc)
                    output = getoutput(cmd)
                    logger.info('\n' + output)
                    break


def call_prescript(prescript):
    logger.info('start to execute pre scripts')
    p=Popen(prescript,shell=True,stdout=PIPE,stderr=PIPE)
    logger.info('-'*20 + 'pre script stdout' + '-'*20)
    ret = p.wait()
    logger.info(p.stdout.read().decode(encoding="utf-8"))
    logger.info('-'*20 + 'pre script stdout' + '-'*20)

    if ret==0:
        logger.info('end of pre scripts, return code is {0}'.format(ret))
    else:
        logger.info('script return code is non-zero, it is {0}'.format(ret))
        sys.exit(1)


def call_postscript(postscript):
    logger.info('start to execute post scripts')
    p=Popen(postscript,shell=True,stdout=PIPE,stderr=PIPE)
    logger.info('-'*20 + 'post script stdout' + '-'*20)
    ret = p.wait()
    logger.info(p.stdout.read().decode(encoding="utf-8"))
    logger.info('-'*20 + 'post script stdout' + '-'*20)

    if ret==0:
        logger.info('end of post scripts, return code is {0}'.format(ret))
    else:
        logger.info('script return code is non-zero, it is {0}'.format(ret))
        sys.exit(1)


args = itmarg_par()        

if 'mq' in args.pclist and not args.qmgr:
    raise UsageExc('mq')
if 'ud' in args.pclist and not args.inst: 
    raise UsageExc('ud')

call_prescript(args.prescript)
cfgitem = TemaCfg(args,hostname)

cfgitem.modify_ini()
cfgitem.run_itmcmd()
cfgitem.modify_kulconfig()
cfgitem.modify_inttab()
cfgitem.modify_startagent()
cfgitem.modify_stopagent()
cfgitem.modify_autostr()
cfgitem.chg_user_group()
cfgitem.chg_permission()
cfgitem.chk_output()

call_postscript(args.postscript)
