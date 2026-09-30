"""Deterministic, localized WhatsApp response models and labels."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Language = Literal["en", "mr", "hi"]


@dataclass(frozen=True)
class BotMessage:
    kind: Literal["text", "buttons", "list", "location"]
    text: str
    buttons: tuple[tuple[str, str], ...] = ()
    rows: tuple[tuple[str, str, str], ...] = ()
    latitude: float | None = None
    longitude: float | None = None
    name: str | None = None
    address: str | None = None


TEXT: dict[str, dict[str, str]] = {
    "choose_language": {
        "en": "Choose your language:\n1. English\n2. मराठी\n3. हिन्दी",
        "mr": "भाषा निवडा:\n1. English\n2. मराठी\n3. हिन्दी",
        "hi": "भाषा चुनें:\n1. English\n2. मराठी\n3. हिन्दी",
    },
    "main_menu": {
        "en": "Main menu\n1. Current allocation\n2. Get recommendations\n3. My requests\n4. Profile / preferences\n5. Change language",
        "mr": "मुख्य मेनू\n1. सध्याचे वाटप\n2. शिफारसी मिळवा\n3. माझ्या विनंत्या\n4. प्रोफाइल / प्राधान्ये\n5. भाषा बदला",
        "hi": "मुख्य मेनू\n1. वर्तमान आवंटन\n2. सिफारिशें प्राप्त करें\n3. मेरी अनुरोध सूची\n4. प्रोफाइल / प्राथमिकताएँ\n5. भाषा बदलें",
    },
    "unknown": {
        "en": "I didn't understand that choice. Reply with one of the listed numbers, or type MENU.",
        "mr": "तो पर्याय समजला नाही. दिलेल्या क्रमांकांपैकी एक पाठवा किंवा MENU लिहा.",
        "hi": "वह विकल्प समझ नहीं आया। दिए गए अंकों में से एक भेजें या MENU लिखें।",
    },
    "help": {
        "en": "Use the numbered choices. You can also type MENU, BACK, CANCEL, or HELP.",
        "mr": "क्रमांकित पर्याय वापरा. MENU, BACK, CANCEL किंवा HELP देखील लिहू शकता.",
        "hi": "क्रमांकित विकल्प चुनें। आप MENU, BACK, CANCEL या HELP भी लिख सकते हैं।",
    },
    "no_allocation": {
        "en": "You do not currently have an active allocation.",
        "mr": "सध्या तुमचे सक्रिय वाटप नाही.",
        "hi": "वर्तमान में आपका कोई सक्रिय आवंटन नहीं है।",
    },
    "no_requests": {
        "en": "No allocation requests were found.",
        "mr": "कोणत्याही वाटप विनंत्या आढळल्या नाहीत.",
        "hi": "कोई आवंटन अनुरोध नहीं मिला।",
    },
    "map_unavailable": {
        "en": "Map reference unavailable.",
        "mr": "नकाशा संदर्भ उपलब्ध नाही.",
        "hi": "मानचित्र संदर्भ उपलब्ध नहीं है।",
    },
    "analytical_reference": {
        "en": "Approximate analytical map reference. This is not a legally verified zone boundary.",
        "mr": "अंदाजे विश्लेषणात्मक नकाशा संदर्भ. ही कायदेशीररीत्या सत्यापित क्षेत्र सीमा नाही.",
        "hi": "अनुमानित विश्लेषणात्मक मानचित्र संदर्भ। यह कानूनी रूप से सत्यापित क्षेत्र सीमा नहीं है।",
    },
    "full_name": {
        "en": "Please enter your full name.",
        "mr": "कृपया तुमचे पूर्ण नाव लिहा.",
        "hi": "कृपया अपना पूरा नाम लिखें।",
    },
    "category": {
        "en": "Choose your business category.",
        "mr": "तुमचा व्यवसाय प्रकार निवडा.",
        "hi": "अपनी व्यवसाय श्रेणी चुनें।",
    },
    "division": {
        "en": "Choose your preferred division.",
        "mr": "तुमचा पसंतीचा विभाग निवडा.",
        "hi": "अपना पसंदीदा विभाग चुनें।",
    },
    "locality": {
        "en": "Enter a preferred locality, or reply SKIP.",
        "mr": "पसंतीचा परिसर लिहा किंवा SKIP पाठवा.",
        "hi": "पसंदीदा क्षेत्र लिखें या SKIP भेजें।",
    },
    "priority": {
        "en": "Choose a priority profile.",
        "mr": "प्राधान्य प्रोफाइल निवडा.",
        "hi": "प्राथमिकता प्रोफाइल चुनें।",
    },
    "market": {
        "en": "Prefer proximity to markets?", "mr": "बाजाराजवळील क्षेत्रांना प्राधान्य द्यायचे?",
        "hi": "क्या बाज़ार के पास के क्षेत्रों को प्राथमिकता दें?",
    },
    "transport": {
        "en": "Prefer public transport access?", "mr": "सार्वजनिक वाहतूक उपलब्धतेला प्राधान्य द्यायचे?",
        "hi": "क्या सार्वजनिक परिवहन सुविधा को प्राथमिकता दें?",
    },
    "parking": {
        "en": "Prefer nearby parking?", "mr": "जवळील पार्किंगला प्राधान्य द्यायचे?",
        "hi": "क्या पास की पार्किंग को प्राथमिकता दें?",
    },
    "recommendations": {
        "en": "Recommended vending zones", "mr": "शिफारस केलेली विक्री क्षेत्रे",
        "hi": "अनुशंसित विक्रय क्षेत्र",
    },
    "score_notice": {
        "en": "Scores are decision-support values, not probabilities.",
        "mr": "गुण हे निर्णय-सहाय्य मूल्य आहेत; संभाव्यता नाहीत.",
        "hi": "स्कोर निर्णय-सहायता मूल्य हैं, संभावनाएँ नहीं।",
    },
    "choose_recommendation": {
        "en": "Reply 1, 2 or 3. You can also reply WHY 1 or MAP 1.",
        "mr": "1, 2 किंवा 3 पाठवा. कारणासाठी WHY 1 किंवा नकाशासाठी MAP 1 पाठवू शकता.",
        "hi": "1, 2 या 3 भेजें। कारण के लिए WHY 1 या मानचित्र के लिए MAP 1 भेज सकते हैं।",
    },
    "yes": {"en": "Yes", "mr": "हो", "hi": "हाँ"},
    "no": {"en": "No", "mr": "नाही", "hi": "नहीं"},
    "profile_updated": {
        "en": "Profile updated.", "mr": "प्रोफाइल अद्ययावत केले.", "hi": "प्रोफाइल अपडेट किया गया।",
    },
    "onboarding_cancelled": {
        "en": "Onboarding cancelled.", "mr": "नोंदणी प्रक्रिया रद्द केली.", "hi": "पंजीकरण प्रक्रिया रद्द की गई।",
    },
    "request_cancelled": {
        "en": "The pending request was cancelled.",
        "mr": "प्रलंबित विनंती रद्द केली.", "hi": "लंबित अनुरोध रद्द किया गया।",
    },
}


CATEGORY_LABELS = {
    "en": {
        "vegetable_fruit": "Vegetables / fruit", "flower": "Flowers",
        "clothing": "Clothing", "general_goods": "General goods",
        "food": "Prepared food", "other": "Other",
    },
    "mr": {
        "vegetable_fruit": "भाजीपाला / फळे", "flower": "फुले",
        "clothing": "कपडे", "general_goods": "सामान्य वस्तू",
        "food": "तयार अन्न", "other": "इतर",
    },
    "hi": {
        "vegetable_fruit": "सब्ज़ियाँ / फल", "flower": "फूल",
        "clothing": "कपड़े", "general_goods": "सामान्य वस्तुएँ",
        "food": "तैयार भोजन", "other": "अन्य",
    },
}

STATUS_LABELS = {
    "en": {"PENDING": "Pending", "APPROVED": "Approved", "REJECTED": "Rejected", "CANCELLED": "Cancelled"},
    "mr": {"PENDING": "प्रलंबित", "APPROVED": "मंजूर", "REJECTED": "नामंजूर", "CANCELLED": "रद्द"},
    "hi": {"PENDING": "लंबित", "APPROVED": "स्वीकृत", "REJECTED": "अस्वीकृत", "CANCELLED": "रद्द"},
}


def tr(key: str, language: str = "en", **values: Any) -> str:
    template = TEXT.get(key, {}).get(language) or TEXT.get(key, {}).get("en") or key
    return template.format(**values)


def text_message(body: str) -> BotMessage:
    return BotMessage("text", body)


def button_message(body: str, buttons: list[tuple[str, str]]) -> BotMessage:
    return BotMessage("buttons", body, buttons=tuple(buttons[:3]))


def list_message(body: str, rows: list[tuple[str, str, str]]) -> BotMessage:
    return BotMessage("list", body, rows=tuple(rows[:10]))


def location_message(latitude: float, longitude: float, name: str, address: str) -> BotMessage:
    return BotMessage(
        "location", address, latitude=latitude, longitude=longitude,
        name=name, address=address,
    )
