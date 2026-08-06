// UI copy per language. Selecting a language switches the whole interface and
// the example query, and is also injected into the model prompt so responses
// come back in the same language.
//
// NOTE: these translations are machine-authored. Have a native speaker review
// them before relying on them in front of an audience.

export interface Strings {
  /** Native name of the language, for the model prompt. */
  nativeName: string
  /** Product name, transliterated into each script rather than translated. */
  productName: string
  navQuery: string
  heroTitle: string
  heroEmphasis: string
  heroSubtitle: string
  placeholder: string
  searchAria: string
  runSearch: string
  askByVoice: string
  stopRecording: string
  discardRecording: string
  lookingFor: string
  spokenRequest: string
  change: string
  whereToLook: string
  uploadFootage: string
  searchLibrary: string
  footage: string
  fileHint: string
  dropHint: string
  findTheMoment: string
  searching: string
  nothingIndexed: string
  nothingIndexedBody: string
  watchingFootage: string
  moments: string
  momentsEmptyPrompt: string
  noMatches: string
  noMatchesBody: string
  resultsFor: string
  searchedFor: string
  viewMoments: string
  newSearch: string
  startOver: string
  navHowItWorks: string
  navUpload: string
  navTests: string
  navDeveloper: string
  matchSuffix: string
  searchFailed: string
  stageUploading: string
  stageDecoding: string
  stageUnderstanding: string
  stageScanning: string
  stageMatching: string
  stageLocalising: string
  stageClipping: string
}

const en: Strings = {
  productName: 'Aperture',
  navQuery: 'Query',
  nativeName: 'English',
  heroTitle: 'Ask your footage',
  heroEmphasis: 'anything',
  heroSubtitle:
    'Natural-language search across video archives, ask in your own language and retrieve the exact moment.',
  placeholder: 'a person opening a red door at night',
  searchAria: 'Search your footage',
  runSearch: 'Run search',
  askByVoice: 'Ask by voice',
  stopRecording: 'Stop recording',
  discardRecording: 'Discard recording',
  lookingFor: 'Looking for',
  spokenRequest: 'Spoken request',
  change: 'Change',
  whereToLook: 'Where should I look?',
  uploadFootage: 'Upload footage',
  searchLibrary: 'Search existing library',
  footage: 'Footage',
  fileHint: 'MP4, WebM, MOV, AVI, or MKV.',
  dropHint: 'Drop a video here, or click to browse',
  findTheMoment: 'Find the moment',
  searching: 'Searching…',
  nothingIndexed: 'Nothing indexed yet',
  nothingIndexedBody:
    'There is no indexed library on this machine right now. Upload footage instead and it will be searched directly.',
  watchingFootage: 'Watching the footage',
  moments: 'Moments',
  momentsEmptyPrompt: 'Ask a question above, then choose the footage to search.',
  noMatches: 'No matching moments',
  noMatchesBody: 'Nothing in this footage matched that description. Try describing it differently.',
  resultsFor: 'Results for',
  searchedFor: 'Searched for',
  viewMoments: 'View moments',
  newSearch: 'New search',
  startOver: 'Start over',
  navHowItWorks: 'How it works',
  navUpload: 'Preprocess',
  navTests: 'Tests',
  navDeveloper: 'Developer',
  matchSuffix: 'match',
  searchFailed: 'The search could not be completed.',
  stageUploading: 'Uploading footage',
  stageDecoding: 'Decoding and probing duration',
  stageUnderstanding: 'Understanding the request',
  stageScanning: 'Scanning visual, audio, and speech',
  stageMatching: 'Matching against the request',
  stageLocalising: 'Localising exact moments',
  stageClipping: 'Cutting playable clips',
}

const hi: Strings = {
  ...en,
  productName: 'अपर्चर',
  navQuery: 'खोज',
  nativeName: 'हिन्दी',
  heroTitle: 'अपने फुटेज से पूछें',
  heroEmphasis: 'कुछ भी',
  heroSubtitle:
    'वीडियो संग्रह में प्राकृतिक भाषा खोज, अपनी भाषा में पूछें और ठीक वही पल पाएँ।',
  placeholder: 'रात में लाल दरवाज़ा खोलता हुआ व्यक्ति',
  searchAria: 'अपने फुटेज में खोजें',
  runSearch: 'खोजें',
  askByVoice: 'बोलकर पूछें',
  stopRecording: 'रिकॉर्डिंग रोकें',
  discardRecording: 'रिकॉर्डिंग हटाएँ',
  lookingFor: 'खोज रहे हैं',
  spokenRequest: 'बोला गया अनुरोध',
  change: 'बदलें',
  whereToLook: 'मुझे कहाँ देखना चाहिए?',
  uploadFootage: 'फुटेज अपलोड करें',
  searchLibrary: 'मौजूदा लाइब्रेरी खोजें',
  footage: 'फुटेज',
  fileHint: 'MP4, WebM, MOV, AVI या MKV।',
  dropHint: 'यहाँ वीडियो छोड़ें, या ब्राउज़ करने के लिए क्लिक करें',
  findTheMoment: 'वह पल खोजें',
  searching: 'खोज रहे हैं…',
  nothingIndexed: 'अभी कुछ भी अनुक्रमित नहीं है',
  nothingIndexedBody:
    'इस मशीन पर अभी कोई अनुक्रमित लाइब्रेरी नहीं है। इसके बजाय फुटेज अपलोड करें, उसे सीधे खोजा जाएगा।',
  watchingFootage: 'फुटेज देखा जा रहा है',
  moments: 'पल',
  momentsEmptyPrompt: 'ऊपर प्रश्न पूछें, फिर खोजने के लिए फुटेज चुनें।',
  noMatches: 'कोई मेल खाता पल नहीं',
  noMatchesBody: 'इस फुटेज में उस विवरण से कुछ मेल नहीं खाया। इसे अलग तरह से बताएँ।',
  resultsFor: 'परिणाम',
  searchedFor: 'खोजा गया',
  viewMoments: 'पल देखें',
  newSearch: 'नई खोज',
  startOver: 'फिर से शुरू करें',
  navHowItWorks: 'यह कैसे काम करता है',
  navUpload: 'प्रीप्रोसेस',
  navTests: 'परीक्षण',
  navDeveloper: 'डेवलपर',
  matchSuffix: 'मेल',
}

const kn: Strings = {
  ...en,
  productName: 'ಅಪರ್ಚರ್',
  navQuery: 'ಹುಡುಕಾಟ',
  nativeName: 'ಕನ್ನಡ',
  heroTitle: 'ನಿಮ್ಮ ದೃಶ್ಯಾವಳಿಯನ್ನು ಕೇಳಿ',
  heroEmphasis: 'ಏನನ್ನಾದರೂ',
  heroSubtitle:
    'ವೀಡಿಯೊ ಸಂಗ್ರಹಗಳಲ್ಲಿ ಸಹಜ ಭಾಷಾ ಹುಡುಕಾಟ, ನಿಮ್ಮ ಭಾಷೆಯಲ್ಲಿ ಕೇಳಿ, ನಿಖರವಾದ ಕ್ಷಣವನ್ನು ಪಡೆಯಿರಿ.',
  placeholder: 'ರಾತ್ರಿ ಕೆಂಪು ಬಾಗಿಲು ತೆರೆಯುತ್ತಿರುವ ವ್ಯಕ್ತಿ',
  searchAria: 'ನಿಮ್ಮ ದೃಶ್ಯಾವಳಿಯಲ್ಲಿ ಹುಡುಕಿ',
  runSearch: 'ಹುಡುಕಿ',
  askByVoice: 'ಧ್ವನಿಯಲ್ಲಿ ಕೇಳಿ',
  stopRecording: 'ರೆಕಾರ್ಡಿಂಗ್ ನಿಲ್ಲಿಸಿ',
  discardRecording: 'ರೆಕಾರ್ಡಿಂಗ್ ತೆಗೆದುಹಾಕಿ',
  lookingFor: 'ಹುಡುಕುತ್ತಿರುವುದು',
  spokenRequest: 'ಮಾತನಾಡಿದ ವಿನಂತಿ',
  change: 'ಬದಲಾಯಿಸಿ',
  whereToLook: 'ನಾನು ಎಲ್ಲಿ ಹುಡುಕಬೇಕು?',
  uploadFootage: 'ದೃಶ್ಯಾವಳಿ ಅಪ್‌ಲೋಡ್ ಮಾಡಿ',
  searchLibrary: 'ಅಸ್ತಿತ್ವದಲ್ಲಿರುವ ಗ್ರಂಥಾಲಯ ಹುಡುಕಿ',
  footage: 'ದೃಶ್ಯಾವಳಿ',
  fileHint: 'MP4, WebM, MOV, AVI ಅಥವಾ MKV.',
  dropHint: 'ಇಲ್ಲಿ ವೀಡಿಯೊ ಬಿಡಿ, ಅಥವಾ ಆಯ್ಕೆ ಮಾಡಲು ಕ್ಲಿಕ್ ಮಾಡಿ',
  findTheMoment: 'ಆ ಕ್ಷಣವನ್ನು ಹುಡುಕಿ',
  searching: 'ಹುಡುಕಲಾಗುತ್ತಿದೆ…',
  nothingIndexed: 'ಇನ್ನೂ ಏನೂ ಸೂಚಿಕೆಯಾಗಿಲ್ಲ',
  nothingIndexedBody:
    'ಈ ಯಂತ್ರದಲ್ಲಿ ಸದ್ಯಕ್ಕೆ ಯಾವುದೇ ಸೂಚಿಕೆ ಗ್ರಂಥಾಲಯವಿಲ್ಲ. ಬದಲಿಗೆ ದೃಶ್ಯಾವಳಿ ಅಪ್‌ಲೋಡ್ ಮಾಡಿ, ಅದನ್ನು ನೇರವಾಗಿ ಹುಡುಕಲಾಗುತ್ತದೆ.',
  watchingFootage: 'ದೃಶ್ಯಾವಳಿ ನೋಡಲಾಗುತ್ತಿದೆ',
  moments: 'ಕ್ಷಣಗಳು',
  momentsEmptyPrompt: 'ಮೇಲೆ ಪ್ರಶ್ನೆ ಕೇಳಿ, ನಂತರ ಹುಡುಕಲು ದೃಶ್ಯಾವಳಿ ಆಯ್ಕೆಮಾಡಿ.',
  noMatches: 'ಹೊಂದಾಣಿಕೆಯ ಕ್ಷಣಗಳಿಲ್ಲ',
  noMatchesBody: 'ಈ ದೃಶ್ಯಾವಳಿಯಲ್ಲಿ ಆ ವಿವರಣೆಗೆ ಏನೂ ಹೊಂದಲಿಲ್ಲ. ಬೇರೆ ರೀತಿಯಲ್ಲಿ ವಿವರಿಸಿ.',
  resultsFor: 'ಫಲಿತಾಂಶಗಳು',
  searchedFor: 'ಹುಡುಕಿದ್ದು',
  viewMoments: 'ಕ್ಷಣಗಳನ್ನು ನೋಡಿ',
  newSearch: 'ಹೊಸ ಹುಡುಕಾಟ',
  startOver: 'ಮತ್ತೆ ಪ್ರಾರಂಭಿಸಿ',
  navHowItWorks: 'ಇದು ಹೇಗೆ ಕೆಲಸ ಮಾಡುತ್ತದೆ',
  navUpload: 'ಪೂರ್ವಸಂಸ್ಕರಣೆ',
  navTests: 'ಪರೀಕ್ಷೆಗಳು',
  navDeveloper: 'ಡೆವಲಪರ್',
  matchSuffix: 'ಹೊಂದಾಣಿಕೆ',
}

const bn: Strings = {
  ...en,
  productName: 'অ্যাপারচার',
  navQuery: 'অনুসন্ধান',
  nativeName: 'বাংলা',
  heroTitle: 'আপনার ফুটেজকে জিজ্ঞাসা করুন',
  heroEmphasis: 'যা খুশি',
  heroSubtitle:
    'ভিডিও সংগ্রহে স্বাভাবিক ভাষায় অনুসন্ধান, নিজের ভাষায় জিজ্ঞাসা করুন এবং সঠিক মুহূর্তটি পান।',
  placeholder: 'রাতে লাল দরজা খুলছেন এমন একজন ব্যক্তি',
  searchAria: 'আপনার ফুটেজে অনুসন্ধান করুন',
  runSearch: 'অনুসন্ধান',
  askByVoice: 'কণ্ঠে জিজ্ঞাসা করুন',
  stopRecording: 'রেকর্ডিং বন্ধ করুন',
  discardRecording: 'রেকর্ডিং বাতিল করুন',
  lookingFor: 'যা খুঁজছেন',
  spokenRequest: 'কথিত অনুরোধ',
  change: 'পরিবর্তন',
  whereToLook: 'আমি কোথায় খুঁজব?',
  uploadFootage: 'ফুটেজ আপলোড করুন',
  searchLibrary: 'বিদ্যমান লাইব্রেরি খুঁজুন',
  footage: 'ফুটেজ',
  fileHint: 'MP4, WebM, MOV, AVI বা MKV।',
  dropHint: 'এখানে ভিডিও ছাড়ুন, বা ব্রাউজ করতে ক্লিক করুন',
  findTheMoment: 'মুহূর্তটি খুঁজুন',
  searching: 'খোঁজা হচ্ছে…',
  nothingIndexed: 'এখনও কিছু সূচিবদ্ধ হয়নি',
  nothingIndexedBody:
    'এই মেশিনে এখন কোনো সূচিবদ্ধ লাইব্রেরি নেই। পরিবর্তে ফুটেজ আপলোড করুন, সেটিই সরাসরি খোঁজা হবে।',
  watchingFootage: 'ফুটেজ দেখা হচ্ছে',
  moments: 'মুহূর্ত',
  momentsEmptyPrompt: 'উপরে প্রশ্ন করুন, তারপর খোঁজার জন্য ফুটেজ বেছে নিন।',
  noMatches: 'মিলে যাওয়া কোনো মুহূর্ত নেই',
  noMatchesBody: 'এই ফুটেজে সেই বর্ণনার সাথে কিছু মেলেনি। অন্যভাবে বর্ণনা করুন।',
  resultsFor: 'ফলাফল',
  searchedFor: 'অনুসন্ধান করা হয়েছে',
  viewMoments: 'মুহূর্ত দেখুন',
  newSearch: 'নতুন অনুসন্ধান',
  startOver: 'আবার শুরু করুন',
  navHowItWorks: 'এটি কীভাবে কাজ করে',
  navUpload: 'প্রিপ্রসেস',
  navTests: 'পরীক্ষা',
  navDeveloper: 'ডেভেলপার',
  matchSuffix: 'মিল',
}

const ta: Strings = {
  ...en,
  productName: 'அப்பர்ச்சர்',
  navQuery: 'தேடல்',
  nativeName: 'தமிழ்',
  heroTitle: 'உங்கள் காணொளியிடம் கேளுங்கள்',
  heroEmphasis: 'எதையும்',
  heroSubtitle:
    'வீடியோ காப்பகங்களில் இயற்கை மொழித் தேடல், உங்கள் மொழியில் கேளுங்கள், சரியான தருணத்தைப் பெறுங்கள்.',
  placeholder: 'இரவில் சிவப்புக் கதவைத் திறக்கும் ஒருவர்',
  searchAria: 'உங்கள் காணொளியில் தேடுங்கள்',
  runSearch: 'தேடு',
  askByVoice: 'குரலில் கேளுங்கள்',
  stopRecording: 'பதிவை நிறுத்து',
  discardRecording: 'பதிவை நீக்கு',
  lookingFor: 'தேடுவது',
  spokenRequest: 'பேசிய கோரிக்கை',
  change: 'மாற்று',
  whereToLook: 'நான் எங்கே தேட வேண்டும்?',
  uploadFootage: 'காணொளியைப் பதிவேற்று',
  searchLibrary: 'இருக்கும் நூலகத்தில் தேடு',
  footage: 'காணொளி',
  fileHint: 'MP4, WebM, MOV, AVI அல்லது MKV.',
  dropHint: 'இங்கே வீடியோவை விடுங்கள், அல்லது தேர்ந்தெடுக்க கிளிக் செய்யுங்கள்',
  findTheMoment: 'அந்தத் தருணத்தைக் கண்டறி',
  searching: 'தேடுகிறது…',
  nothingIndexed: 'இதுவரை எதுவும் அட்டவணைப்படுத்தப்படவில்லை',
  nothingIndexedBody:
    'இந்த இயந்திரத்தில் இப்போது அட்டவணைப்படுத்தப்பட்ட நூலகம் இல்லை. மாறாக காணொளியைப் பதிவேற்றுங்கள், அது நேரடியாகத் தேடப்படும்.',
  watchingFootage: 'காணொளி பார்க்கப்படுகிறது',
  moments: 'தருணங்கள்',
  momentsEmptyPrompt: 'மேலே கேள்வி கேளுங்கள், பிறகு தேட காணொளியைத் தேர்ந்தெடுங்கள்.',
  noMatches: 'பொருந்தும் தருணங்கள் இல்லை',
  noMatchesBody: 'இந்தக் காணொளியில் அந்த விவரிப்புக்கு எதுவும் பொருந்தவில்லை. வேறு விதமாக விவரியுங்கள்.',
  resultsFor: 'முடிவுகள்',
  searchedFor: 'தேடியது',
  viewMoments: 'தருணங்களைப் பார்',
  newSearch: 'புதிய தேடல்',
  startOver: 'மீண்டும் தொடங்கு',
  navHowItWorks: 'இது எப்படி வேலை செய்கிறது',
  navUpload: 'முன்செயலாக்கம்',
  navTests: 'சோதனைகள்',
  navDeveloper: 'உருவாக்குநர்',
  matchSuffix: 'பொருத்தம்',
}

const te: Strings = {
  ...en,
  productName: 'అపర్చर్',
  navQuery: 'శోధన',
  nativeName: 'తెలుగు',
  heroTitle: 'మీ ఫుటేజ్‌ను అడగండి',
  heroEmphasis: 'ఏదైనా',
  heroSubtitle:
    'వీడియో ఆర్కైవ్‌లలో సహజ భాషా శోధన, మీ భాషలో అడగండి, ఖచ్చితమైన క్షణాన్ని పొందండి.',
  placeholder: 'రాత్రి ఎర్రటి తలుపు తెరుస్తున్న వ్యక్తి',
  searchAria: 'మీ ఫుటేజ్‌లో వెతకండి',
  runSearch: 'వెతకండి',
  askByVoice: 'గొంతుతో అడగండి',
  stopRecording: 'రికార్డింగ్ ఆపండి',
  discardRecording: 'రికార్డింగ్ తొలగించండి',
  lookingFor: 'వెతుకుతున్నది',
  spokenRequest: 'మాట్లాడిన అభ్యర్థన',
  change: 'మార్చండి',
  whereToLook: 'నేను ఎక్కడ వెతకాలి?',
  uploadFootage: 'ఫుటేజ్ అప్‌లోడ్ చేయండి',
  searchLibrary: 'ఉన్న లైబ్రరీలో వెతకండి',
  footage: 'ఫుటేజ్',
  fileHint: 'MP4, WebM, MOV, AVI లేదా MKV.',
  dropHint: 'ఇక్కడ వీడియో వదలండి, లేదా ఎంచుకోవడానికి క్లిక్ చేయండి',
  findTheMoment: 'ఆ క్షణాన్ని కనుగొనండి',
  searching: 'వెతుకుతోంది…',
  nothingIndexed: 'ఇంకా ఏదీ ఇండెక్స్ చేయలేదు',
  nothingIndexedBody:
    'ఈ మెషీన్‌లో ప్రస్తుతం ఇండెక్స్ చేసిన లైబ్రరీ లేదు. బదులుగా ఫుటేజ్ అప్‌లోడ్ చేయండి, అది నేరుగా వెతకబడుతుంది.',
  watchingFootage: 'ఫుటేజ్ చూస్తోంది',
  moments: 'క్షణాలు',
  momentsEmptyPrompt: 'పైన ప్రశ్న అడగండి, తర్వాత వెతకడానికి ఫుటేజ్ ఎంచుకోండి.',
  noMatches: 'సరిపోలే క్షణాలు లేవు',
  noMatchesBody: 'ఈ ఫుటేజ్‌లో ఆ వివరణకు ఏదీ సరిపోలలేదు. వేరే విధంగా వివరించండి.',
  resultsFor: 'ఫలితాలు',
  searchedFor: 'వెతికినది',
  viewMoments: 'క్షణాలను చూడండి',
  newSearch: 'కొత్త శోధన',
  startOver: 'మళ్లీ ప్రారంభించండి',
  navHowItWorks: 'ఇది ఎలా పనిచేస్తుంది',
  navUpload: 'ప్రీప్రాసెస్',
  navTests: 'పరీక్షలు',
  navDeveloper: 'డెవలపర్',
  matchSuffix: 'సరిపోలిక',
}

const mr: Strings = {
  ...hi,
  nativeName: 'मराठी',
  heroTitle: 'तुमच्या फुटेजला विचारा',
  heroEmphasis: 'काहीही',
  heroSubtitle:
    'व्हिडिओ संग्रहात नैसर्गिक भाषेत शोध, तुमच्या भाषेत विचारा आणि नेमका क्षण मिळवा.',
  placeholder: 'रात्री लाल दरवाजा उघडणारी व्यक्ती',
  runSearch: 'शोधा',
  lookingFor: 'शोधत आहात',
  whereToLook: 'मी कुठे पाहू?',
  uploadFootage: 'फुटेज अपलोड करा',
  searchLibrary: 'सध्याची लायब्ररी शोधा',
  findTheMoment: 'तो क्षण शोधा',
  searching: 'शोधत आहे…',
  moments: 'क्षण',
  newSearch: 'नवीन शोध',
  startOver: 'पुन्हा सुरू करा',
}

const gu: Strings = {
  ...hi,
  nativeName: 'ગુજરાતી',
  heroTitle: 'તમારા ફૂટેજને પૂછો',
  heroEmphasis: 'કંઈપણ',
  heroSubtitle:
    'વિડિઓ સંગ્રહમાં કુદરતી ભાષામાં શોધ, તમારી ભાષામાં પૂછો અને ચોક્કસ ક્ષણ મેળવો.',
  placeholder: 'રાત્રે લાલ દરવાજો ખોલતી વ્યક્તિ',
  runSearch: 'શોધો',
  lookingFor: 'શોધી રહ્યા છો',
  whereToLook: 'મારે ક્યાં જોવું?',
  uploadFootage: 'ફૂટેજ અપલોડ કરો',
  searchLibrary: 'હાલની લાઇબ્રેરી શોધો',
  findTheMoment: 'તે ક્ષણ શોધો',
  searching: 'શોધી રહ્યું છે…',
  moments: 'ક્ષણો',
  newSearch: 'નવી શોધ',
  startOver: 'ફરી શરૂ કરો',
}

const ml: Strings = {
  ...en,
  productName: 'അപ്പർച്ചർ',
  navQuery: 'തിരയൽ',
  nativeName: 'മലയാളം',
  heroTitle: 'നിങ്ങളുടെ ദൃശ്യങ്ങളോട് ചോദിക്കൂ',
  heroEmphasis: 'എന്തും',
  heroSubtitle:
    'വീഡിയോ ശേഖരങ്ങളിൽ സ്വാഭാവിക ഭാഷാ തിരയൽ, നിങ്ങളുടെ ഭാഷയിൽ ചോദിക്കൂ, കൃത്യമായ നിമിഷം കണ്ടെത്തൂ.',
  placeholder: 'രാത്രിയിൽ ചുവന്ന വാതിൽ തുറക്കുന്ന ഒരാൾ',
  runSearch: 'തിരയുക',
  lookingFor: 'തിരയുന്നത്',
  whereToLook: 'ഞാൻ എവിടെ നോക്കണം?',
  uploadFootage: 'ദൃശ്യങ്ങൾ അപ്‌ലോഡ് ചെയ്യുക',
  searchLibrary: 'നിലവിലുള്ള ലൈബ്രറി തിരയുക',
  findTheMoment: 'ആ നിമിഷം കണ്ടെത്തുക',
  searching: 'തിരയുന്നു…',
  moments: 'നിമിഷങ്ങൾ',
  newSearch: 'പുതിയ തിരയൽ',
  startOver: 'വീണ്ടും തുടങ്ങുക',
}

const pa: Strings = {
  ...hi,
  nativeName: 'ਪੰਜਾਬੀ',
  heroTitle: 'ਆਪਣੀ ਫੁਟੇਜ ਤੋਂ ਪੁੱਛੋ',
  heroEmphasis: 'ਕੁਝ ਵੀ',
  heroSubtitle:
    'ਵੀਡੀਓ ਸੰਗ੍ਰਹਿ ਵਿੱਚ ਕੁਦਰਤੀ ਭਾਸ਼ਾ ਖੋਜ, ਆਪਣੀ ਭਾਸ਼ਾ ਵਿੱਚ ਪੁੱਛੋ ਅਤੇ ਠੀਕ ਪਲ ਲੱਭੋ।',
  placeholder: 'ਰਾਤ ਨੂੰ ਲਾਲ ਦਰਵਾਜ਼ਾ ਖੋਲ੍ਹਦਾ ਵਿਅਕਤੀ',
  runSearch: 'ਖੋਜੋ',
  lookingFor: 'ਲੱਭ ਰਹੇ ਹੋ',
  whereToLook: 'ਮੈਂ ਕਿੱਥੇ ਵੇਖਾਂ?',
  uploadFootage: 'ਫੁਟੇਜ ਅੱਪਲੋਡ ਕਰੋ',
  searchLibrary: 'ਮੌਜੂਦਾ ਲਾਇਬ੍ਰੇਰੀ ਖੋਜੋ',
  findTheMoment: 'ਉਹ ਪਲ ਲੱਭੋ',
  searching: 'ਖੋਜ ਰਿਹਾ ਹੈ…',
  moments: 'ਪਲ',
  newSearch: 'ਨਵੀਂ ਖੋਜ',
  startOver: 'ਮੁੜ ਸ਼ੁਰੂ ਕਰੋ',
}

const or_: Strings = {
  ...en,
  productName: 'ଆପରଚର',
  navQuery: 'ସନ୍ଧାନ',
  nativeName: 'ଓଡ଼ିଆ',
  heroTitle: 'ଆପଣଙ୍କ ଫୁଟେଜକୁ ପଚାରନ୍ତୁ',
  heroEmphasis: 'ଯାହା ବି',
  heroSubtitle:
    'ଭିଡିଓ ସଂଗ୍ରହରେ ସ୍ୱାଭାବିକ ଭାଷା ସନ୍ଧାନ, ନିଜ ଭାଷାରେ ପଚାରନ୍ତୁ ଏବଂ ସଠିକ୍ ମୁହୂର୍ତ୍ତ ପାଆନ୍ତୁ।',
  placeholder: 'ରାତିରେ ଲାଲ୍ କବାଟ ଖୋଲୁଥିବା ଜଣେ ବ୍ୟକ୍ତି',
  runSearch: 'ଖୋଜନ୍ତୁ',
  lookingFor: 'ଖୋଜୁଛନ୍ତି',
  whereToLook: 'ମୁଁ କେଉଁଠି ଖୋଜିବି?',
  uploadFootage: 'ଫୁଟେଜ ଅପଲୋଡ୍ କରନ୍ତୁ',
  searchLibrary: 'ବିଦ୍ୟମାନ ଲାଇବ୍ରେରୀ ଖୋଜନ୍ତୁ',
  findTheMoment: 'ସେହି ମୁହୂର୍ତ୍ତ ଖୋଜନ୍ତୁ',
  searching: 'ଖୋଜୁଛି…',
  moments: 'ମୁହୂର୍ତ୍ତ',
  newSearch: 'ନୂଆ ସନ୍ଧାନ',
  startOver: 'ପୁଣି ଆରମ୍ଭ କରନ୍ତୁ',
}

const ur: Strings = {
  ...en,
  productName: 'اپرچر',
  navQuery: 'تلاش',
  nativeName: 'اردو',
  heroTitle: 'اپنی فوٹیج سے پوچھیں',
  heroEmphasis: 'کچھ بھی',
  heroSubtitle:
    'ویڈیو آرکائیوز میں فطری زبان میں تلاش, اپنی زبان میں پوچھیں اور عین وہی لمحہ حاصل کریں۔',
  placeholder: 'رات کو سرخ دروازہ کھولتا ہوا شخص',
  runSearch: 'تلاش کریں',
  lookingFor: 'تلاش کر رہے ہیں',
  whereToLook: 'میں کہاں دیکھوں؟',
  uploadFootage: 'فوٹیج اپ لوڈ کریں',
  searchLibrary: 'موجودہ لائبریری تلاش کریں',
  findTheMoment: 'وہ لمحہ تلاش کریں',
  searching: 'تلاش جاری ہے…',
  moments: 'لمحات',
  newSearch: 'نئی تلاش',
  startOver: 'دوبارہ شروع کریں',
}

const sa: Strings = {
  ...hi,
  nativeName: 'संस्कृतम्',
  heroTitle: 'स्वचित्रपटं पृच्छतु',
  heroEmphasis: 'किमपि',
  heroSubtitle:
    'चलच्चित्रसंग्रहेषु स्वाभाविकभाषया अन्वेषणम्, स्वभाषया पृच्छतु, यथार्थं क्षणं प्राप्नोतु।',
  placeholder: 'रात्रौ रक्तद्वारम् उद्घाटयन् जनः',
  runSearch: 'अन्विष्यताम्',
  lookingFor: 'अन्विष्यते',
  whereToLook: 'कुत्र अन्वेषणीयम्?',
  uploadFootage: 'चित्रपटम् आरोपयतु',
  searchLibrary: 'विद्यमानं संग्रहम् अन्विष्यताम्',
  findTheMoment: 'तं क्षणम् अन्विष्यताम्',
  searching: 'अन्विष्यते…',
  moments: 'क्षणाः',
  newSearch: 'नवम् अन्वेषणम्',
  startOver: 'पुनः आरभताम्',
}

const STRINGS: Record<string, Strings> = {
  english: en,
  hindi: hi,
  kannada: kn,
  bengali: bn,
  tamil: ta,
  telugu: te,
  marathi: mr,
  gujarati: gu,
  malayalam: ml,
  punjabi: pa,
  odia: or_,
  urdu: ur,
  sanskrit: sa,
}

export const RTL_LANGUAGES = new Set(['urdu'])

export function stringsFor(language: string): Strings {
  return STRINGS[language] ?? en
}
