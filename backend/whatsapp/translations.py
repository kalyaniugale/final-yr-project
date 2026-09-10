"""Fixed reviewed-in-code templates; official place descriptions remain unchanged."""
LANGUAGES = ("en", "mr", "hi")
STRINGS = {
    "welcome": ("Welcome! Choose a language.", "स्वागत! भाषा निवडा.", "स्वागत! भाषा चुनें।"),
    "menu": ("How can we help?", "कशी मदत करू?", "हम कैसे मदद करें?"),
    "find": ("Find location", "जागा शोधा", "जगह खोजें"),
    "help": ("Zone help", "क्षेत्र मदत", "क्षेत्र सहायता"),
    "help_text": ("We compare exploratory vending references using your business and preferred division. This is not registration, booking or permission. Listed capacity is not vacancy. Send menu to change language.", "व्यवसाय व पसंतीच्या विभागानुसार संदर्भ स्थळांची तुलना केली जाते. ही नोंदणी, आरक्षण किंवा परवानगी नाही. नमूद क्षमता म्हणजे रिक्त जागा नाही. भाषा बदलण्यासाठी menu पाठवा.", "व्यवसाय और पसंदीदा विभाग से संदर्भ स्थानों की तुलना होती है। यह पंजीकरण, बुकिंग या अनुमति नहीं है। दर्ज क्षमता खाली जगह नहीं है। भाषा बदलने के लिए menu भेजें।"),
    "vendor": ("Choose your situation.", "आपली स्थिती निवडा.", "अपनी स्थिति चुनें।"),
    "new": ("New vendor", "नवीन विक्रेता", "नया विक्रेता"),
    "existing": ("Existing / relocate", "स्थलांतर", "स्थान बदलना"),
    "manual": ("Choose your business and division manually. We do not verify registration or infer your current location.", "व्यवसाय व विभाग स्वतः निवडा. नोंदणीची पडताळणी किंवा सध्याच्या जागेचा अंदाज केला जात नाही.", "व्यवसाय और विभाग स्वयं चुनें। पंजीकरण सत्यापन या वर्तमान स्थान का अनुमान नहीं किया जाता।"),
    "business": ("Choose your business. Examples share one model category.", "व्यवसाय निवडा. उदाहरणे एकाच मॉडेल वर्गात येऊ शकतात.", "व्यवसाय चुनें। उदाहरण एक ही मॉडल श्रेणी में आ सकते हैं।"),
    "division": ("Choose a preferred division.", "पसंतीचा विभाग निवडा.", "पसंदीदा विभाग चुनें।"),
    "any": ("Any division", "कोणताही विभाग", "कोई भी विभाग"),
    "choose": ("Choose", "निवडा", "चुनें"),
    "next": ("More options", "आणखी पर्याय", "और विकल्प"),
    "results": ("Your top {count} suitable location references:", "आपल्यासाठी सर्वोत्तम {count} संदर्भ स्थळे:", "आपके लिए शीर्ष {count} उपयुक्त संदर्भ स्थान:"),
    "index": ("Suitability Index", "योग्यता निर्देशांक", "उपयुक्तता सूचकांक"),
    "select": ("Select a location reference.", "संदर्भ स्थळ निवडा.", "संदर्भ स्थान चुनें।"),
    "zone": ("Option {rank}", "पर्याय {rank}", "विकल्प {rank}"),
    "fallback": ("Outside your preferred division.", "आपल्या पसंतीच्या विभागाबाहेर.", "आपके पसंदीदा विभाग के बाहर।"),
    "actions": ("Choose what to view.", "काय पाहायचे ते निवडा.", "क्या देखना है चुनें।"),
    "simple": ("Simple explanation", "सोपे स्पष्टीकरण", "सरल विवरण"),
    "detailed": ("Detailed analysis", "सविस्तर विश्लेषण", "विस्तृत विश्लेषण"),
    "map": ("View map", "नकाशा पहा", "नक्शा देखें"),
    "back": ("Recommendations", "शिफारसी", "सुझाव"),
    "restart": ("Start again", "पुन्हा सुरू करा", "फिर शुरू करें"),
    "navigation": ("Back to results or start again. Send menu to change language.", "शिफारसींकडे परत जा किंवा पुन्हा सुरू करा. भाषा बदलण्यासाठी menu पाठवा.", "सुझाव पर लौटें या फिर शुरू करें। भाषा बदलने के लिए menu भेजें।"),
    "invalid_choice": ("Please use the current menu. Old selections may have expired.", "सध्याचा मेनू वापरा. जुने पर्याय कालबाह्य असू शकतात.", "वर्तमान मेनू का उपयोग करें। पुराने विकल्प समाप्त हो सकते हैं।"),
    "unknown": ("Unknown", "अज्ञात", "अज्ञात"),
    "empty": ("No references match. Try a different business or division.", "जुळणारे संदर्भ नाहीत. दुसरा व्यवसाय किंवा विभाग निवडा.", "कोई संदर्भ नहीं मिला। दूसरा व्यवसाय या विभाग चुनें।"),
    "timeout": ("The backend took too long. Please try again.", "उत्तर मिळण्यास उशीर झाला. पुन्हा प्रयत्न करा.", "उत्तर में देर हुई। फिर कोशिश करें।"),
    "unavailable": ("Recommendations are temporarily unavailable. Please try again.", "शिफारसी सध्या उपलब्ध नाहीत. पुन्हा प्रयत्न करा.", "सुझाव अभी उपलब्ध नहीं हैं। फिर कोशिश करें।"),
    "unexpected": ("The backend returned an unexpected response. Please try again later.", "अनपेक्षित उत्तर मिळाले. नंतर प्रयत्न करा.", "अप्रत्याशित उत्तर मिला। बाद में कोशिश करें।"),
    "invalid": ("The business or division is no longer supported. Please start again.", "व्यवसाय किंवा विभाग आता समर्थित नाही. पुन्हा सुरू करा.", "व्यवसाय या विभाग अब समर्थित नहीं है। फिर शुरू करें।"),
    "caveat": ("Exploratory index, not success probability, vacancy or permission. Historical records are not current occupancy; map coverage is incomplete.", "हा शोधात्मक निर्देशांक आहे; यशाची शक्यता, रिक्त जागा किंवा परवानगी नाही. ऐतिहासिक नोंदी म्हणजे सध्याची उपस्थिती नाही; नकाशा माहिती अपूर्ण आहे.", "यह खोजपरक सूचकांक है, सफलता की संभावना, खाली जगह या अनुमति नहीं। ऐतिहासिक रिकॉर्ड वर्तमान उपस्थिति नहीं हैं; नक्शे की जानकारी अधूरी है।"),
    "map_name": ("Approximate location reference", "अंदाजे स्थान संदर्भ", "अनुमानित स्थान संदर्भ"),
    "map_caveat": ("This is an analytical reference point, not an exact stall, verified official boundary, or confirmed allocation.", "हा विश्लेषणासाठी संदर्भ बिंदू आहे; अचूक गाळा, पडताळलेली अधिकृत सीमा किंवा निश्चित वाटप नाही.", "यह विश्लेषण का संदर्भ बिंदु है, सटीक स्टॉल, सत्यापित आधिकारिक सीमा या निश्चित आवंटन नहीं।"),
    "shared": ("This environmental reference is shared by {count} zone records. Confirm the exact site locally.", "हा पर्यावरणीय संदर्भ {count} क्षेत्र नोंदींमध्ये सामायिक आहे. अचूक जागा स्थानिक पातळीवर तपासा.", "यह पर्यावरणीय संदर्भ {count} क्षेत्र रिकॉर्ड साझा करते हैं। सटीक स्थान स्थानीय स्तर पर जाँचें।"),
    "no_map": ("No valid map point is available for this zone. Use its official description and confirm locally.", "या क्षेत्रासाठी वैध नकाशा बिंदू नाही. अधिकृत वर्णन वापरून स्थानिक पडताळणी करा.", "इस क्षेत्र का मान्य नक्शा बिंदु उपलब्ध नहीं है। आधिकारिक विवरण से स्थानीय पुष्टि करें।"),
    "business_fact": ("Historical records: {same} same-category associations among {total} associations here.", "ऐतिहासिक नोंदी: येथील {total} संबंधांपैकी {same} आपल्या व्यवसाय वर्गातील.", "ऐतिहासिक रिकॉर्ड: यहाँ {total} संबंधों में {same} आपके व्यवसाय की श्रेणी के हैं।"),
    "commercial_fact": ("Mapped markets within 500 m: {markets}; commercial places within 250 m: {shops}.", "५०० मीटरमधील नोंदवलेले बाजार: {markets}; २५० मीटरमधील व्यावसायिक स्थळे: {shops}.", "५०० मीटर में दर्ज बाजार: {markets}; २५० मीटर में व्यावसायिक स्थान: {shops}।"),
    "access_fact": ("Reference-point distance: major road {road} m; mapped bus access {bus} m.", "संदर्भ बिंदूपासून अंतर: मुख्य रस्ता {road} मीटर; नोंदवलेला बस प्रवेश {bus} मीटर.", "संदर्भ बिंदु से दूरी: मुख्य सड़क {road} मीटर; दर्ज बस पहुँच {bus} मीटर।"),
    "facilities_fact": ("Within 500 m, mapped healthcare: {health}; education: {education}; toilets: {toilets}; parking: {parking}.", "५०० मीटरमध्ये नोंदवलेली आरोग्य स्थळे: {health}; शिक्षण: {education}; शौचालये: {toilets}; पार्किंग: {parking}.", "५०० मीटर में दर्ज स्वास्थ्य स्थल: {health}; शिक्षा: {education}; शौचालय: {toilets}; पार्किंग: {parking}।"),
    "preference_fact": ("Division: {division}.", "विभाग: {division}.", "विभाग: {division}।"),
    "historical_fact": ("This comparison uses {total} historical associations, not current occupancy.", "या तुलनेत {total} ऐतिहासिक संबंध वापरले आहेत; सध्याची उपस्थिती नाही.", "यह तुलना {total} ऐतिहासिक संबंधों पर आधारित है, वर्तमान उपस्थिति पर नहीं।"),
    "metrics": ("Factor score: {score}/100 | Weight: {weight}% | Base contribution: {contribution} points", "घटक गुण: {score}/१०० | वजन: {weight}% | मूळ योगदान: {contribution} गुण", "घटक अंक: {score}/१०० | भार: {weight}% | मूल योगदान: {contribution} अंक"),
    "coverage": ("MCDA coverage: {coverage}. Overall index = sum of base contributions / coverage. Missing factors are omitted; contributions do not directly sum to the index when coverage is below 1.", "MCDA कव्हरेज: {coverage}. एकूण निर्देशांक = मूळ योगदानांची बेरीज / कव्हरेज. माहिती नसलेले घटक वगळले जातात; कव्हरेज १ पेक्षा कमी असल्यास बेरीज थेट निर्देशांक नसते.", "MCDA कवरेज: {coverage}। कुल सूचकांक = मूल योगदानों का योग / कवरेज। अज्ञात घटक हटाए जाते हैं; कवरेज १ से कम हो तो योग सीधे सूचकांक नहीं है।"),
}

CATEGORIES = {
    "vegetable_fruit": (("Fruits & Vegetables", "फळे व भाज्या", "फल और सब्जियाँ"), ("Fresh vegetables, fruits and produce", "ताज्या भाज्या व फळे", "ताजी सब्जियाँ और फल")),
    "food": (("Food & Beverages", "खाद्य व पेये", "खाद्य और पेय"), ("Tea, coffee, juice, snacks and prepared food", "चहा, कॉफी, रस, नाश्ता व तयार अन्न", "चाय, कॉफी, रस, नाश्ता और तैयार भोजन")),
    "clothing": (("Clothing", "कपडे", "कपड़े"), ("Clothes and garments", "कपडे व वस्त्रे", "कपड़े और वस्त्र")),
    "flower": (("Flowers", "फुले", "फूल"), ("Flowers, garlands and flower products", "फुले, हार व फुलांच्या वस्तू", "फूल, माला और फूलों के उत्पाद")),
    "general_goods": (("General Goods", "सामान्य वस्तू", "सामान्य सामान"), ("Household and daily-use goods", "घरगुती व दैनंदिन वस्तू", "घरेलू और दैनिक उपयोग का सामान")),
    "other": (("Other", "इतर", "अन्य"), ("Other supported vending businesses", "इतर समर्थित विक्री व्यवसाय", "अन्य समर्थित विक्रय व्यवसाय")),
}

FACTOR_LABELS = {
    "business": ("Business compatibility", "व्यवसाय सुसंगती", "व्यवसाय अनुकूलता"),
    "commercial": ("Commercial surroundings", "व्यावसायिक परिसर", "व्यावसायिक परिवेश"),
    "access": ("Road and transport access", "रस्ता व वाहतूक प्रवेश", "सड़क और परिवहन पहुँच"),
    "facilities": ("Nearby facilities", "जवळच्या सुविधा", "आसपास की सुविधाएँ"),
    "preference": ("Preferred division", "पसंतीचा विभाग", "पसंदीदा विभाग"),
    "historical": ("Historical evidence", "ऐतिहासिक पुरावा", "ऐतिहासिक साक्ष्य"),
}

FACTOR_DETAILS = {
    "business": ("Historical business concentration is smoothed and weak evidence shrunk toward neutral; it does not measure sales.", "ऐतिहासिक व्यवसाय एकाग्रता समायोजित होते; कमी पुरावा तटस्थ मूल्याकडे आणला जातो. यात विक्री मोजली जात नाही.", "ऐतिहासिक व्यवसाय संकेंद्रण समायोजित होता है; कमजोर साक्ष्य तटस्थ मान की ओर जाता है। यह बिक्री नहीं मापता।"),
    "commercial": ("Mapped commercial activity is context, not measured footfall or guaranteed demand.", "नोंदवलेली व्यावसायिक स्थळे संदर्भ आहेत; मोजलेली गर्दी किंवा निश्चित मागणी नाही.", "दर्ज व्यावसायिक गतिविधि संदर्भ है, मापी गई भीड़ या निश्चित माँग नहीं।"),
    "access": ("Distances and road density describe reference access, not pedestrian safety.", "अंतरे व रस्त्यांची घनता संदर्भ प्रवेश दर्शवतात; पादचारी सुरक्षितता नाही.", "दूरी और सड़क घनत्व संदर्भ पहुँच बताते हैं, पैदल सुरक्षा नहीं।"),
    "facilities": ("Map counts describe surroundings. Missing records do not prove absence.", "नकाशावरील संख्या परिसर दर्शवतात. नोंद नसणे म्हणजे सुविधा नसणे नाही.", "नक्शे की गिनती परिवेश बताती है। रिकॉर्ड न होना अनुपस्थिति का प्रमाण नहीं।"),
    "preference": ("Local candidates are selected first; other divisions fill a shortfall.", "स्थानिक पर्याय आधी निवडले जातात; कमी पडल्यास इतर विभाग वापरले जातात.", "स्थानीय विकल्प पहले चुने जाते हैं; कम होने पर अन्य विभागों से लिए जाते हैं।"),
    "historical": ("Association volume is historical evidence, not occupancy or success. This manual flow uses the full reference registry.", "संबंधांची संख्या ऐतिहासिक पुरावा आहे; उपस्थिती किंवा यश नाही. या स्वनिवड प्रवाहात पूर्ण संदर्भ नोंदणी वापरली जाते.", "संबंधों की संख्या ऐतिहासिक साक्ष्य है, उपस्थिति या सफलता नहीं। इस मैनुअल प्रवाह में पूरी संदर्भ सूची उपयोग होती है।"),
}


def localized(values, lang):
    return values[LANGUAGES.index(lang)]


def t(lang, key, **values):
    return localized(STRINGS[key], lang).format(**values)
