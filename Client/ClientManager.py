import ast
import os
import pickle
import struct
import sys
import threading
import time
import zlib
from multiprocessing import Process, Queue
# from asyncio import Queue
from enum import Enum, unique
from typing import Union, ByteString, Text, Tuple, Dict, Callable, Any, List
import requests
from utils import *
import signal
from events import *

URL = "http://oj.sustech.xyz:8000"


class ClientManager:
    def __init__(self) -> None:
        self.__event = Event()
        self.__audio_in_event = Event()
        self.__audio_out_event = Event()
        self.__simple_manager: Union[SimpleManager, None] = None
        self.__screen_manager: Union[ScreenManager, None] = None
        self.__simple_receiver: Union[SimpleReceiver, None] = None
        self.__screen_receiver: Union[ScreenReceiver, None] = None
        self.__audio_receiver: Union[AudioReceiver, None] = None
        self.__audio_manager: Union[AudioManager, None] = None

        self._mode: ClientMode = ClientMode.INIT
        self._session = requests.Session()

        self._control_connection: Client = Client()
        self._control_queue: Queue = self._control_connection.queue
        self._control_connection.run()
        self.__control_event: Event = Event()

        self.__simple_process: Union[Process, None] = None
        self.__screen_process: Union[Process, None] = None
        self.__audio_process_in: Union[Process, None] = None
        self.__audio_process_out: Union[Process, None] = None

        self.__control_thread: Union[Thread, None] = Thread(target=self.control_FSA)
        self.__control_thread.setDaemon(True)
        self.__control_thread.start()

        self.__self = str(time.time_ns())

        self.__audio_status: int = 0  # -1 force 0 disable 1 enable
        self.__video_status: int = 0  # 0 down 1 up
        self.__video_sharer: str = ''
        self.__is_owner: bool = False
        self.__is_admin: bool = False

        self.__checking_user: str = ''
        self.__check: int = 0

        self.__getting_list: bool = True
        self.__tmp_list: str = ''

        self.__meeting_list: Dict[str, Dict[str, Any]] = dict()
        """
        is_admin, is_owner, video, audio
        """

        self.__username: str = ""
        self.__token: str = ""

    def delay(self) -> int:
        printf(get_message(SendEvent.NetworkDelay, (str(self._control_connection.delay),)))
        return self._control_connection.delay

    def display_name(self):
        printf(get_message(SendEvent.DisplayName, (self.__username,)))
        return self.__username

    def logout(self):
        printf(get_message(SendEvent.Okay, ()))
        self._mode = ClientMode.INIT

    def connected(self) -> None:
        printf(get_message(SendEvent.ClientReady, ()))

    def token(self) -> None:
        printf(get_message(SendEvent.Okay, (self.__token,)))

    @staticmethod
    def _url(_url: str) -> str:
        return f"{URL}/{_url}" if _url[0] != '/' else f"{URL}{_url}"

    @property
    def mode(self) -> ClientMode:
        return self._mode

    @staticmethod
    def create_connection() -> Client:
        return Client()

    def reset_control(self) -> None:
        self.__control_event.set()
        time.sleep(1)
        try:
            self.__control_thread._stop()
        except Exception:
            pass
        self._control_connection.close()
        self._control_connection: Client = Client()
        self._control_queue: Queue = self._control_connection.queue
        self._control_connection.run()
        self.__control_event: Event = Event()
        self.__control_thread: Union[Thread, None] = Thread(target=self.control_FSA)
        self.__control_thread.setDaemon(True)
        self.__control_thread.start()

    def reset_meeting(self) -> None:
        self.reset_control()
        self.__getting_list = True
        self.__meeting_list = dict()
        self.__is_owner = self.__is_admin = False
        self.__audio_status: int = 0  # -1 force 0 disable 1 enable
        self.__video_status: int = 0  # 0 down 1 up
        self.__video_sharer: str = ''
        self.__check = False
        self.__checking_user = ''

    def change_name(self, username) -> None:
        data = dict(
            newname=username
        )
        try:
            response = self._session.post(url=self._url('/changename/'), data=data)
            data = response.json()
            if data.get('status', 500) != 200:
                printf(get_message(SendEvent.Failed, ()))
            self.__username = username

            printf(get_message(SendEvent.Okay, ()))
        except Exception:
            printf(get_message(SendEvent.Failed, ()))

    def change_password(self, password: str) -> None:
        data = dict(
            password=password
        )
        try:
            response = self._session.post(url=self._url('/changepwd/'), data=data)
            data = response.json()
            if data.get('status', 500) != 200:
                printf(get_message(SendEvent.Failed, ()))
            printf(get_message(SendEvent.Okay, ()))
        except Exception:
            printf(get_message(SendEvent.Failed, ()))

    def register(self, username: str, password: str) -> None:
        data = dict(
            username=username,
            password=password
        )
        try:
            response = self._session.post(url=self._url('/register/'), data=data)
            data = response.json()
            if data.get('status', 500) != 200:
                printf(get_message(SendEvent.Failed, ()))
            self._mode = ClientMode.LOGIN
            self.__username = username
            self.__token = data['token']
            printf(get_message(SendEvent.Okay, ()))
        except Exception:
            printf(get_message(SendEvent.Failed, ()))

    def login(self, username: str, password: str) -> None:
        data = dict(
            username=username,
            password=password
        )
        try:
            response = self._session.post(url=self._url('/login/'), data=data)
            data = response.json()
            if data.get('status', 500) != 200:
                printf(get_message(SendEvent.Failed, ()))
            self._mode = ClientMode.LOGIN
            self.__username = username
            self.__token = data['token']
            printf(get_message(SendEvent.Okay, ()))
        except Exception:
            printf(get_message(SendEvent.Failed, ()))

    def change_token(self) -> None:
        try:
            response = self._session.post(url=self._url('/changetoken/'))
            data = response.json()
            if data.get('status', 500) != 200:
                printf(get_message(SendEvent.Failed, ()))
            self.__token = data['token']
            printf(get_message(SendEvent.Okay, (self.__token,)))
        except Exception:
            printf(get_message(SendEvent.Failed, ()))

    def create_meeting(self, password) -> None:
        try:
            token = str(time.time_ns())[-9:]
            self.__token = token
            data = dict(token=token, password=password)
            response = self._session.post(url=self._url('/createmeeting/'), data=data)
            data = response.json()
            if data.get('status', 500) != 200:
                printf(get_message(SendEvent.Failed, ()))
            self.__token = token
            printf(get_message(SendEvent.Okay, (self.__token,)))
        except Exception:
            printf(get_message(SendEvent.Failed, ()))

    @staticmethod
    def get_level(owner: bool, admin: bool) -> int:
        if owner:
            return 2
        if admin:
            return 1
        return 0

    def get_member(self) -> str:
        return '||||'.join('####'.join((_, str(self.get_level(i['is_owner'], i['is_admin'])),
                                        str(max(i['audio'], 0)))) for _, i in self.__meeting_list.items())

    def control_FSA(self):
        """
        CONTROL : START/STOP : DO/DONE : token : uuid

        MEETING: AUDIO : token : uuid : DISABLE/ENABLE : username
        MEETING: VIDEO : token : uuid : DISABLE/ENABLE : username
        MEETING: MESSAGE : token : uuid : msg : username
        MEETING: OWNER : token : uuid : username : new_name
        MEETING: ADMIN : token : uuid : username : new_name
        MEETING: JOIN : token : uuid : username : audio
        MEETING: LEAVE : token : uuid : username
        MEETING: SHUTDOWN : token: uuid
        MEETING: CHECK : token : uuid : username : DO/DONE
        MEETING: GET : token : uuid : msg
        :return:
        """
        debug('start control-----------------')
        while not self.__control_event.is_set():
            if self._control_connection.queue.empty():
                time.sleep(1)
                continue
            op: bytes = self._control_connection.queue.get()
            op: Sequence[Union[str, Union[int, dict]]] = ast.literal_eval(op.decode('utf-8'))
            debug('control receive-----------------' + str(op))
            if op[0] == 'CONTROL':
                if self.__token != op[3] or op[4] == self.__self:
                    continue
                if op[1] == 'START':
                    if op[2] == 'DO':
                        if self.__screen_process:
                            self.__screen_process.kill()
                        self.__screen_manager = ScreenManager(self.__token, self.__event)
                        self.__simple_receiver = SimpleReceiver(self.__token, self.__event)
                        self.__screen_manager.init_msg = LISTEN(f"{self.__token}_screen")
                        self.__simple_receiver.init_msg = LISTEN(f"{self.__token}_simple")
                        self.__screen_process = get_process(self.__screen_manager)
                        self.__simple_process = get_process(self.__simple_receiver)
                        self.__screen_process.daemon = True
                        self.__simple_process.daemon = True
                        self.__simple_process.start()
                        self.__screen_process.start()
                        self._control_connection.send(str(('CONTROL', 'START', 'DONE', self.__token, self.__self)))
                        printf(get_message(SendEvent.StartControl, ()))
                        self._mode = ClientMode.LISTENER
                    else:
                        if self.__screen_process:
                            self.__screen_process.kill()
                        self.__screen_receiver = ScreenReceiver(self.__token, self.__event)
                        self.__simple_manager = SimpleManager(self.__token, self.__event)
                        self.__screen_receiver.init_msg = CONTROL(f"{self.__token}_screen")
                        self.__simple_manager.init_msg = CONTROL(f"{self.__token}_simple")
                        self.__screen_process = get_process(self.__screen_receiver)
                        self.__simple_process = get_process(self.__simple_manager)
                        self.__simple_process.daemon = True
                        self.__screen_process.daemon = True
                        self.__simple_process.start()
                        self.__screen_process.start()
                        self._mode = ClientMode.CONTROLLER
                else:
                    printf(get_message(SendEvent.EndControl, ()))
                    if self.__screen_process:
                        self.__screen_process.terminate()
                        self.__screen_process.kill()
            elif op[0] == 'MEETING':
                if self.__token != op[2] or op[3] == self.__self:
                    continue
                if self.__getting_list and op[1] != 'GET':
                    continue
                if op[1] == 'CHECK':
                    if op[5] == 'DO':
                        if self.__meeting_list.get(op[4], dict()).get('is_admin', False) or \
                                self.__meeting_list.get(op[4], dict()).get('is_owner', False):
                            pass
                    else:
                        if self.__checking_user == op[4]:
                            self.__check += 1
                elif op[1] == 'GET':
                    if len(op) == 4:
                        if self.__getting_list:
                            continue
                        self._control_connection.send(str((*op[:3], self.__self, self.__meeting_list)))
                    else:
                        for name, value in op[4].items():
                            if name not in self.__meeting_list:
                                self.__meeting_list[name] = value
                        self.__getting_list = False
                elif op[1] == 'AUDIO':
                    if op[4] == 'DISABLE':
                        if op[5] == self.__username:
                            self.__audio_status = -1
                            self.clear_audio(out_only=True)
                            printf(get_message(SendEvent.UpdateAudio, ('0',)))
                        self.__meeting_list[op[5]]['audio'] = 0
                    elif op[4] == 'ENABLE':
                        if op[5] == self.__username:
                            if self.__audio_status == -1:
                                self.__audio_status = 0
                                self.__meeting_list[op[5]]['audio'] = 0
                            printf(get_message(SendEvent.UpdateAudio, (str(max(self.__audio_status, 0)),)))
                        else:
                            self.__meeting_list[op[5]]['audio'] = 1
                            # self.start_audio_manager()
                    else:
                        if op[5] == self.__username:
                            if self.__audio_status == -1:
                                self.__audio_status = 0
                                self.__meeting_list[op[5]]['audio'] = 0
                    debug('++++++++\n')
                    debug(self.get_member())
                    debug('++++++++\n')
                    printf(get_message(SendEvent.UpdateMembers, (self.get_member(),)))
                elif op[1] == 'MESSAGE':
                    printf(get_message(SendEvent.UpdateMessage, (op[5], op[4])))
                elif op[1] == 'OWNER':
                    if self.__meeting_list[op[4]]['is_owner']:
                        self.__meeting_list[op[4]]['is_owner'] = False
                        self.__meeting_list[op[5]]['is_owner'] = True
                        if op[5] == self.__username:
                            self.__is_owner = True
                            printf(get_message(SendEvent.UpdateLevel, (2,)))
                    printf(get_message(SendEvent.UpdateMembers, (self.get_member(),)))
                elif op[1] == 'ADMIN':
                    if self.__meeting_list[op[4]]['is_owner']:
                        self.__meeting_list[op[5]]['is_admin'] = not self.__meeting_list[op[5]]['is_admin']
                        if op[5] == self.__username:
                            self.__is_admin = not self.__is_admin
                            printf(
                                get_message(SendEvent.UpdateLevel, (str(self.get_level(self.__is_owner, self.__is_admin)),)))
                        printf(get_message(SendEvent.UpdateMembers, (self.get_member(),)))
                elif op[1] == 'JOIN':
                    if op[4] in self.__meeting_list:
                        continue
                    self.__meeting_list[op[4]] = dict(
                        is_admin=False,
                        is_owner=False,
                        video=0,
                        audio=op[5]
                    )
                    printf(get_message(SendEvent.UpdateMembers, (self.get_member(),)))
                elif op[1] == 'LEAVE':
                    if op[4] in self.__meeting_list:
                        if self.__meeting_list[op[4]]['is_owner']:
                            printf(get_message(SendEvent.ForceExit, ('end',)))
                            self.stop()
                            return
                        self.__meeting_list.pop(op[4])
                        printf(get_message(SendEvent.UpdateMembers, (self.get_member(),)))
                    if op[4] == self.__username:
                        printf(get_message(SendEvent.ForceExit, ('force',)))
                        self.stop()
                        return
                elif op[1] == 'VIDEO':
                    if self.__screen_process:
                        self.__screen_process.terminate()
                        self.__screen_process.kill()
                    if op[4] == 'DISABLE':
                        self.__meeting_list[op[5]]['video'] = 0
                        printf(get_message(SendEvent.UpdateShare, ('',)))
                    else:
                        self.__meeting_list[op[5]]['video'] = 1
                        self.start_screen_listener()
                        printf(get_message(SendEvent.UpdateShare, (op[5],)))
            else:
                pass

    def clear_audio(self, out_only: bool = True):
        if self.__audio_process_out:
            self.__audio_out_event.set()
            time.sleep(1)
            self.__audio_out_event = Event()
            self.__audio_process_out.terminate()
            self.__audio_process_out.kill()
        if out_only:
            return
        if self.__audio_process_in:
            self.__audio_in_event.set()
            time.sleep(1)
            self.__audio_in_event = Event()
            self.__audio_process_in.terminate()
            self.__audio_process_in.kill()

    def start_audio_manager(self):
        self.__audio_manager = AudioManager(self.__token, self.__audio_out_event)
        self.__audio_manager.init_msg = LISTEN(f"{self.__token}_audio")
        self.__audio_process_out = get_process(self.__audio_manager)
        self.__audio_process_out.daemon = True
        self.__audio_process_out.start()

    def start_audio_listener(self):
        self.__audio_receiver = AudioReceiver(self.__token, self.__audio_in_event)
        self.__audio_receiver.init_msg = CONTROL(f"{self.__token}_audio")
        self.__audio_process_in = get_process(self.__audio_receiver)
        self.__audio_process_in.daemon = True
        self.__audio_process_in.start()

    def start_screen_manager(self):
        self.__screen_manager = ScreenManager(self.__token, self.__event)
        self.__screen_manager.init_msg = LISTEN(f"{self.__token}_screen")
        self.__screen_process = get_process(self.__screen_manager)
        self.__screen_process.daemon = True
        self.__screen_process.start()

    def start_screen_listener(self):
        self.__screen_receiver = ScreenReceiver(self.__token, self.__event)
        self.__screen_receiver.init_msg = CONTROL(f"{self.__token}_screen")
        self.__screen_process = get_process(self.__screen_receiver)
        self.__screen_process.daemon = True
        self.__screen_process.start()

    def listen(self) -> None:
        try:
            self._control_connection.send(str(('control', self.__token)))
            printf(get_message(SendEvent.Okay, ()))
        except Exception:
            return

    def control(self, ID: str) -> bool:
        self.__token = ID
        self._control_connection.send(str(('control', self.__token)))
        time.sleep(0.5)
        self._control_connection.send(str(('CONTROL', 'START', 'DO', self.__token, self.__self)))
        for i in range(3):
            time.sleep(i + 0.1)
            if self._mode == ClientMode.CONTROLLER:
                break
        if self._mode == ClientMode.CONTROLLER:
            printf(get_message(SendEvent.Okay, ()))
        else:
            printf(get_message(SendEvent.Failed, ()))
        return True

    def join_meeting(self, token: str, password: str, audio: str):
        if self.__getting_list:
            self.reset_meeting()
        audio = 1 if audio == 'true' else 0
        data = dict(token=token, password=password)
        response = self._session.post(url=self._url('/checkmeeting/'), data=data)
        data = response.json()
        if data.get('status', 500) != 200:
            printf(get_message(SendEvent.Failed, ()))
            return
        self.__token = token
        self.__is_owner = data.get('is_owner', False)
        self.__audio_status = audio
        self._control_connection.send(str(('control', self.__token)))
        time.sleep(1)
        self._control_connection.send(str(('MEETING', 'GET', self.__token, self.__self)))
        debug('sent control message')

        for i in range(3):
            time.sleep(i + 1)
            if not self.__getting_list:
                break
        if not self.__is_owner:
            if self.__getting_list:
                printf(get_message(SendEvent.Failed, ()))
                return
        self.__getting_list = False
        self.__meeting_list[self.__username] = dict(
            is_admin=False,
            is_owner=self.__is_owner,
            video=0,
            audio=audio
        )
        for i, j in self.__meeting_list.items():
            if j['video']:
                self.__video_sharer = i
                self.start_screen_listener()
                break
        printf(get_message(SendEvent.Okay, ()))
        time.sleep(3)
        printf(get_message(SendEvent.UpdateInfo, (self.__token, self.__username)))
        printf(get_message(SendEvent.UpdateLevel, (str(self.get_level(self.__is_owner, self.__is_admin)),)))
        self._control_connection.send(str(('MEETING', 'JOIN', self.__token, self.__self, self.__username, audio)))
        printf(get_message(SendEvent.UpdateMembers, (self.get_member(),)))
        if audio:
            printf(get_message(SendEvent.UpdateAudio, (str(1),)))
            self.start_audio_manager()
        self.start_audio_listener()
        if self.__video_sharer:
            printf(get_message(SendEvent.UpdateShare, (self.__video_sharer,)))

    def leave_meeting(self, name: str):
        if name != self.__username:
            if not self.__is_owner and not self.__is_admin:
                printf(get_message(SendEvent.Failed, ()))
                return
        if self.__is_owner and name == self.__username:
            data = dict(token=self.__token)
            response = self._session.post(url=self._url('/deletemeeting/'), data=data)
            data = response.json()
            if data.get('status', 500) != 200:
                printf(get_message(SendEvent.Failed, ()))
                return
        printf(get_message(SendEvent.Okay, ()))
        if self.__meeting_list[name]['video']:
            self._control_connection.send(str(('MEETING', 'VIDEO', self.__token, self.__self, 'DISABLE', name)))
        self._control_connection.send(str(('MEETING', 'LEAVE', self.__token, self.__self, name)))
        time.sleep(1)
        self.reset_meeting()
        if self.__screen_process:
            self.__screen_process.terminate()
            self.__screen_process.kill()
        self.clear_audio()

    def change_owner(self, new_name: str):
        if not self.__is_owner:
            printf(get_message(SendEvent.Failed, ()))
        data = dict(token=self.__token, username=new_name)
        response = self._session.post(url=self._url('/changeowner/'), data=data)
        data = response.json()
        if data.get('status', 500) != 200:
            printf(get_message(SendEvent.Failed, ()))
            return

        self._control_connection.send(str(('MEETING', 'OWNER', self.__token, self.__self, self.__username, new_name)))
        self.__is_owner = False
        self.__meeting_list[self.__username]['is_owner'] = False
        self.__meeting_list[new_name]['is_owner'] = True

        printf(get_message(SendEvent.Okay, ()))
        printf(get_message(SendEvent.UpdateLevel, ('0',)))
        printf(get_message(SendEvent.UpdateMembers, (self.get_member(),)))

    def change_admin(self, name: str):
        if not self.__is_owner:
            printf(get_message(SendEvent.Failed, ()))
        self._control_connection.send(
            str(('MEETING', 'ADMIN', self.__token, self.__self, self.__username, name)))
        self.__meeting_list[name]['is_admin'] = not self.__meeting_list[name]['is_admin']
        printf(get_message(SendEvent.Okay, ()))
        printf(get_message(SendEvent.UpdateMembers, (self.get_member(),)))

    def change_audio(self, name: str, others: str = 'false'):
        op = 0
        others = False if others == 'false' else True
        if name == self.__username:
            if self.__audio_status == -1:
                printf(get_message(SendEvent.Failed, ("您已被禁言，请稍候再试！",)))
                return
            else:
                self.__audio_status = 1 - self.__audio_status
                op = self.__audio_status
                self.__meeting_list[self.__username]['audio'] = self.__audio_status
        else:
            if self.__is_admin or self.__is_owner:
                if self.__meeting_list[name]['audio'] == 1:
                    self.__meeting_list[name]['audio'] = 0
                    op = 0
                else:
                    op = 2
            else:
                printf(get_message(SendEvent.Failed, ()))
                return
        if op == 1:
            self._control_connection.send(
                str(('MEETING', 'AUDIO', self.__token, self.__self, 'ENABLE', name)))
            if name == self.__username:
                self.start_audio_manager()
        elif op == 0:
            self._control_connection.send(
                str(('MEETING', 'AUDIO', self.__token, self.__self, 'DISABLE', name)))
            if name == self.__username:
                self.clear_audio(out_only=True)
        else:
            self._control_connection.send(
                str(('MEETING', 'AUDIO', self.__token, self.__self, 'SET', name)))
        printf(get_message(SendEvent.Okay, ()))
        printf(get_message(SendEvent.UpdateAudio, (str(max(self.__audio_status, 0)),)))
        printf(get_message(SendEvent.UpdateMembers, (self.get_member(),)))

    def change_video(self):
        if self.__video_status == 1:
            self._control_connection.send(
                str(('MEETING', 'VIDEO', self.__token, self.__self, 'DISABLE', self.__username)))
            self.__video_status = 0
            # self.__screen_process.terminate()
            # self.__screen_process.kill()
            printf(get_message(SendEvent.Okay, ()))
            printf(get_message(SendEvent.UpdateShare, ('',)))
            self.__meeting_list[self.__username]['video'] = self.__video_status
            if self.__screen_process:
                self.__screen_process.terminate()
                self.__screen_process.kill()
            self.start_screen_listener()
            return
        op = True
        for _, j in self.__meeting_list.items():
            if j['video']:
                op = False
                break
        if not op:
            printf(get_message(SendEvent.Failed, ()))
            return
        self.__video_status = 1
        self._control_connection.send(
            str(('MEETING', 'VIDEO', self.__token, self.__self, 'ENABLE', self.__username)))
        self.__meeting_list[self.__username]['video'] = self.__video_status
        if self.__screen_process:
            self.__screen_process.terminate()
            self.__screen_process.kill()
        self.start_screen_manager()
        printf(get_message(SendEvent.Okay, ()))
        printf(get_message(SendEvent.UpdateShare, (self.__username,)))

    def send_message(self, msg: str):
        self._control_connection.send(
            str(('MEETING', 'MESSAGE', self.__token, self.__self, msg, self.__username)))
        printf(get_message(SendEvent.Okay, ()))
        printf(get_message(SendEvent.UpdateMessage, (self.__username, msg)))

    def stop_control_listen(self):
        self._control_connection.send(str(('CONTROL', 'STOP', 'DO', self.__token, self.__self)))

    def stop(self):
        self.__event.set()
        if self.__screen_process:
            self.__screen_process.terminate()
            self.__screen_process.kill()
        self.clear_audio()
        printf(get_message(SendEvent.Okay, ()))

    def stop_control(self):
        self.__event.set()
        if self.__screen_process:
            self.__screen_process.terminate()
            self.__screen_process.kill()
        printf(get_message(SendEvent.Okay, ()))


manager = ClientManager()
HANDLED_SIGNALS = (
    signal.SIGINT,  # Unix signal 2. Sent by Ctrl+C.
    signal.SIGTERM,  # Unix signal 15. Sent by `kill <pid>`.
)


def signal_handler(a, b):
    debug('killing')
    manager.stop()


if __name__ == '__main__':
    for sig in HANDLED_SIGNALS:
        signal.signal(sig, signal_handler)

    FUNCTIONHASH: Dict[ReceiveEvent, Callable] = {
        ReceiveEvent.DisplayReady: manager.connected,
        ReceiveEvent.DisplayName: manager.display_name,
        ReceiveEvent.NetworkDelay: manager.delay,
        ReceiveEvent.UserLogout: manager.logout,
        ReceiveEvent.UserLogin: manager.login,
        ReceiveEvent.ChangeName: manager.change_name,
        ReceiveEvent.ChangePassword: manager.change_password,
        ReceiveEvent.RemoteControl: manager.control,
        ReceiveEvent.EnableSlave: manager.listen,
        ReceiveEvent.DisableSlave: manager.stop_control_listen,
        ReceiveEvent.GetCode: manager.token,
        ReceiveEvent.RefreshCode: manager.change_token,
        ReceiveEvent.UserRegister: manager.register,
        ReceiveEvent.CreateMeeting: manager.create_meeting,
        ReceiveEvent.TerminateControl: manager.stop_control,
        ReceiveEvent.ExitMeeting: manager.leave_meeting,
        ReceiveEvent.StartShare: manager.change_video,
        ReceiveEvent.EndShare: manager.change_video,
        ReceiveEvent.EnableAudio: manager.change_audio,
        ReceiveEvent.DisableAudio: manager.change_audio,
        ReceiveEvent.SendMessage: manager.send_message,
        ReceiveEvent.SetAdmin: manager.change_admin,
        ReceiveEvent.GiveHost: manager.change_owner,
        ReceiveEvent.JoinMeeting: manager.join_meeting,
        ReceiveEvent.ConfirmExit: manager.stop
    }
    while True:
        ans = scanf()
        # os.write(2, b'rec')
        for event, data in ans:
            if not event:
                continue
            FUNCTIONHASH[event](*data)
            if event == ReceiveEvent.ConfirmExit:
                sys.exit(0)
        # os.write(2, b'done')
    #
    #
    #
    # # op = input()
    # # printf('client-ready')
    # # op = input()
    # y = ClientManager()
    # x = ClientManager()
    # # getattr(y, '_simple_connection')
    #
    # y.login('1', '1')
    # x.login('1', '1')
    # y.control('1')
    #
    # x.listen()
    #
    # print('inp')
    # c = input()
    # print('stop')
    # x.stop()
    # y.stop()
    # sys.exit(0)
    #
    # # x.stop()
    # # print('1111111111111111111111')
