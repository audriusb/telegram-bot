import os
import time
import math
import maidenhead as mh
import logging
import urllib.request

import paho.mqtt.client as mqtt

from html.parser import HTMLParser
from dotenv import load_dotenv
from telegram.ext import (
    Updater,
    Filters,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
)
from telegram import ParseMode, InlineKeyboardMarkup, InlineKeyboardButton, ChatAction
from threading import Thread

load_dotenv()
updater = Updater(token=os.environ.get("TELEGRAM_BOT_TOKEN"), use_context=True)
dispatcher = updater.dispatcher

start_text = "Labas - aš esu LY1BWB stoties botas."
roof_camera_host = "http://192.168.42.177/cgi-bin/hi3510/"
roof_camera_url = roof_camera_host + "snap.cgi?&-getpic"

lower_camera_url = "http://192.168.42.10/webcam/webcam3.jpg"
rig_camera_url = "http://192.168.42.10/webcam/webcam1.jpg"
main_camera_url = (
    "http://192.168.42.183/onvifsnapshot/media_service/snapshot?channel=1&subtype=0"
)

mqtt_host = "192.168.42.253"
vhf_rig_freq = "000000000"
vhf_rig_mode = "FT8"

vhf_rot_az = 0
vhf_rot_el = 0

CAM, FREQ, AZ, EL, MODE = range(5)

valid_users = {
    "LY2EN",
    "sutemos",
    "LY1LB",
    "LY0NAS",
    "LY5AT",
    "LY1WS",
    "LY2DC",
    "LY1JA",
}

home_qth = "KO24PR15"

log = logging
log.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)


class webcam_parser(HTMLParser):
    roof_camera_img = ""

    def handle_startendtag(self, tag, attrs):
        if tag == "img":
            self.roof_camera_img = roof_camera_host + attrs[0][1]
            logging.info("Found IMG: " + self.roof_camera_img)


def log_func(name, update):
    log.info(f"Called {name} by {update.message.from_user['username']}")


def start(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text=start_text)


def angle_between_loc(x1, y1, x2, y2):
    return math.degrees(math.atan2(y2 - y1, x2 - x1)) + 180


def angle_qth(loc_qth):
    (x1, y1) = mh.to_location(loc_qth)
    (x2, y2) = mh.to_location(home_qth)
    return angle_between_loc(x1, y1, x2, y2)


def lower_camera(update, context):
    log_func("lower_camera()", update)
    web_file = urllib.request.urlopen(lower_camera_url)
    context.bot.send_photo(chat_id=update.effective_chat.id, photo=web_file.read())


def rig_camera(update, context):
    log_func("rig_camera()", update)
    web_file = urllib.request.urlopen(rig_camera_url)
    context.bot.send_photo(chat_id=update.effective_chat.id, photo=web_file.read())


def main_camera(update, context):
    log_func("main_camera()", update)
    context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )
    web_file = urllib.request.urlopen(main_camera_url)
    context.bot.send_photo(chat_id=update.effective_chat.id, photo=web_file.read())


def roof_camera(update, context):
    log_func("roof_camera()", update)
    context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )
    web_cam_url = urllib.request.urlopen(roof_camera_url)
    web_cam_html = web_cam_url.read()
    parser = webcam_parser()
    parser.feed(web_cam_html.decode("utf-8"))
    web_file = urllib.request.urlopen(parser.roof_camera_img)
    context.bot.send_photo(chat_id=update.effective_chat.id, photo=web_file.read())


def mqtt_rotator_loop():
    mqtt_loop("VURK/rotator/vhf/#", read_mqtt_rotator_azel)


def mqtt_radio_loop():
    mqtt_loop("VURK/radio/FT847/#", read_mqtt_vhf_freq)


def mqtt_loop(topic, handler):
    mqtt_client = mqtt.Client()
    mqtt_client.connect(mqtt_host, 1883, 60)
    log.info("Connected to MQTT")
    mqtt_client.on_message = handler
    mqtt_client.subscribe(topic)
    log.info(f"Subscribed to MQTT: {topic}")
    mqtt_client.loop_forever()


def read_mqtt_rotator_azel(client, userdata, message):
    global vhf_rot_az
    global vhf_rot_el
    payload_value = str(message.payload.decode("utf-8"))
    if message.topic == "VURK/rotator/vhf/azimuth":
        vhf_rot_az = payload_value
    if message.topic == "VURK/rotator/vhf/elevation":
        vhf_rot_el = payload_value
    if message.topic == "VURK/rotator/vhf/direction":
        pass


def read_mqtt_vhf_freq(client, userdata, message):
    global vhf_rig_freq
    global vhf_rig_mode
    payload_value = str(message.payload.decode("utf-8"))
    if message.topic == "VURK/radio/FT847/frequency":
        vhf_rig_freq = payload_value
    if message.topic == "VURK/radio/FT847/mode":
        vhf_rig_mode = payload_value


def set_vhf_az(update, context):
    log_func("set_vhf_az()", update)
    username = update.message.from_user["username"]
    if len(context.args) > 0 and check_permissions(username, update, context):
        change_az(context.args[-1])
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Suku VHF antenas iš {vhf_rot_az}º į {context.args[-1]}º",
        )
    else:
        options = [
            [
                InlineKeyboardButton(text="0º (N)", callback_data="0"),
                InlineKeyboardButton(text="90º (E)", callback_data="90"),
                InlineKeyboardButton(text="180º (S)", callback_data="180"),
                InlineKeyboardButton(text="270º (W)", callback_data="270"),
            ],
            [
                InlineKeyboardButton(text="Kaunas", callback_data="286"),
                InlineKeyboardButton(text="Klaipėda", callback_data="294"),
                InlineKeyboardButton(text="Šiauliai", callback_data="318"),
                InlineKeyboardButton(text="Panevėžys", callback_data="333"),
            ],
            [
                InlineKeyboardButton(text="Utena", callback_data="13"),
                InlineKeyboardButton(text="Alytus", callback_data="246"),
                InlineKeyboardButton(text="Gardinas", callback_data="220"),
                InlineKeyboardButton(text="Minskas", callback_data="121"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(options)
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Pasirinkite arba įveskite azimutą (dabar: {vhf_rot_az}º):",
            reply_markup=reply_markup,
        )
        return AZ


def check_permissions(username, update, context):
    if username in valid_users:
        return True
    else:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Neturite tokių teisių.",
        )
        return False


def read_vhf_az(update, context):
    query = update.callback_query
    query.answer()
    username = query.from_user["username"]
    if check_permissions(username, update, context):
        change_az(query.data)
        query.edit_message_text(
            text=f"Suku VHF antenas iš {vhf_rot_az}º į {query.data}º"
        )
    return


def change_az(degrees):
    _mqtt_publish("VURK/rotator/vhf/set/azimuth", degrees)
    return


def change_freq(freq):
    _mqtt_publish("VURK/radio/FT847/set/frequency", freq)
    return


def change_mode(mode):
    _mqtt_publish("VURK/radio/FT847/set/mode", mode)
    return


def _mqtt_publish(topic, message):
    mqtt_client = mqtt.Client()
    mqtt_client.connect(mqtt_host, 1883, 60)
    log.info("Connected publisher to MQTT")
    mqtt_client.publish(topic, message)
    log.debug(f"Published {message} to {topic}")
    mqtt_client.disconnect()
    log.info("Disconnected publisher from MQTT (this is OK)")
    return


def set_vhf_mode(update, context):
    log.info(f"Called set_vhf_mode() by {update.message.from_user['username']}")
    username = update.message.from_user["username"]
    if len(context.args) > 0 and check_permissions(username, update, context):
        change_mode(context.args[-1])
        f1 = vhf_rig_mode
        f2 = context.args[-1]
        context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Keičiu režimą iš {f1} į {f2}"
        )
    else:
        options = [
            [
                InlineKeyboardButton(text="FM", callback_data="FM"),
                InlineKeyboardButton(text="USB", callback_data="USB"),
                InlineKeyboardButton(text="LSB", callback_data="LSB"),
            ],
            [
                InlineKeyboardButton(text="CW", callback_data="CW"),
                InlineKeyboardButton(text="CWR", callback_data="CWR"),
                InlineKeyboardButton(text="AM", callback_data="AM"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(options)
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Pasirinkite režimą (dabar {vhf_rig_mode}):",
            reply_markup=reply_markup,
        )
        return MODE


def read_vhf_mode(update, context):
    log.info(f"Called read_vhf_mode()")
    query = update.callback_query
    query.answer()
    username = query.from_user["username"]
    f1 = vhf_rig_mode
    f2 = query.data
    if check_permissions(username, update, context):
        change_mode(query.data)
        query.edit_message_text(text=f"Keičiu režimą iš {f1} į {f2}")
    return


def set_vhf_freq(update, context):
    log.info(f"Called set_vhf_freq() by {update.message.from_user['username']}")
    username = update.message.from_user["username"]
    if len(context.args) > 0 and check_permissions(username, update, context):
        change_freq(context.args[-1])
        f1 = _format_frequency(vhf_rig_freq)
        f2 = _format_frequency(context.args[-1])
        context.bot.send_message(
            chat_id=update.effective_chat.id, text=f"Keičiu dažnį iš {f1} į {f2}"
        )
    else:
        options = [
            [
                InlineKeyboardButton(text="144.050", callback_data="144050000"),
                InlineKeyboardButton(text="144.300", callback_data="144300000"),
                InlineKeyboardButton(text="144.800", callback_data="144800000"),
            ],
            [
                InlineKeyboardButton(text="145.500", callback_data="145500000"),
                InlineKeyboardButton(text="145.800", callback_data="145800000"),
                InlineKeyboardButton(text="145.825", callback_data="145825000"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(options)
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="Pasirinkite arba įveskite dažnį:",
            reply_markup=reply_markup,
        )
        return FREQ


def read_vhf_freq(update, context):
    log.info(f"Called read_vhf_freq()")
    query = update.callback_query
    query.answer()
    username = query.from_user["username"]
    f1 = _format_frequency(vhf_rig_freq)
    f2 = _format_frequency(query.data)
    if check_permissions(username, update, context):
        change_freq(query.data)
        query.edit_message_text(text=f"Keičiu dažnį iš {f1} į {f2}")
    return


def vhf_azel(update, context):
    az = vhf_rot_az
    el = vhf_rot_el
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"VHF antenų azimutas: {az}º, elevacija: {el}º",
        parse_mode=ParseMode.HTML,
    )


def _format_frequency(f):
    return f[-9] + f[-8] + f[-7] + "." + f[-6] + f[-5] + f[-4] + " MHz"


def vhf_freq(update, context):
    ff = _format_frequency(vhf_rig_freq)
    msg = (
        "VHF stoties dažnis: \n<b>"
        + ff
        + " ("
        + vhf_rig_mode
        + ")</b>"
        + "\n👉 <a href='http://sdr.vhf.lt:8000/ft847'>Klausyti gyvai</a>"
    )
    context.bot.send_message(
        chat_id=update.effective_chat.id, text=msg, parse_mode=ParseMode.HTML
    )


def calculate_azimuth_by_loc(update, context):
    user_id = update.message.from_user["id"]
    loc = update.message.text
    deg = round(angle_qth(loc))
    # update.message.reply_text(f"Band set to: {band}")
    context.bot.send_message(
        chat_id=update.effective_chat.id, text=f"Azimutas į {loc} yra {deg}°"
    )
    context.bot.send_message(
        chat_id=update.effective_chat.id, text=f"/set_vhf_az {deg}"
    )


vhf_freq_handler = ConversationHandler(
    entry_points=[
        CommandHandler("set_vhf_freq", set_vhf_freq),
    ],
    states={
        FREQ: [CallbackQueryHandler(read_vhf_freq)],
    },
    fallbacks=[CommandHandler("set_vhf_freq", set_vhf_freq)],
)


vhf_az_handler = ConversationHandler(
    entry_points=[CommandHandler("set_vhf_az", set_vhf_az)],
    states={AZ: [CallbackQueryHandler(read_vhf_az)]},
    fallbacks=[CommandHandler("set_vhf_az", set_vhf_az)],
)

vhf_mode_handler = ConversationHandler(
    entry_points=[CommandHandler("set_vhf_mode", set_vhf_mode)],
    states={MODE: [CallbackQueryHandler(read_vhf_mode)]},
    fallbacks=[CommandHandler("set_vhf_mode", set_vhf_mode)],
)

dispatcher.add_handler(CommandHandler("start", start))

dispatcher.add_handler(CommandHandler("roof_camera", roof_camera))

dispatcher.add_handler(CommandHandler("rig_camera", rig_camera))

dispatcher.add_handler(CommandHandler("lower_camera", lower_camera))

dispatcher.add_handler(CommandHandler("main_camera", main_camera))

dispatcher.add_handler(CommandHandler("vhf_freq", vhf_freq))

dispatcher.add_handler(CommandHandler("vhf_azel", vhf_azel))

dispatcher.add_handler(vhf_freq_handler)

dispatcher.add_handler(vhf_az_handler)

dispatcher.add_handler(vhf_mode_handler)

dispatcher.add_handler(
    MessageHandler(
        Filters.regex(
            r"^\w{2}\d{2}\w{2}(\d\d){0,1}$",
        ),
        calculate_azimuth_by_loc,
    )
)


if __name__ == "__main__":
    telegram_thread = Thread(target=updater.start_polling)
    telegram_thread.start()
    mqtt_rig_thread = Thread(target=mqtt_radio_loop)
    mqtt_rig_thread.start()
    mqtt_rot_thread = Thread(target=mqtt_rotator_loop)
    mqtt_rot_thread.start()
