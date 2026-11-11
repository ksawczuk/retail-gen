"""Static lookup lists: names, places, catalogue vocabulary. All fictional or generic."""

# (formal name, nickname or None)
FIRST_NAMES = [
    ("William", "Bill"), ("Robert", "Bob"), ("Elizabeth", "Liz"), ("Katherine", "Kate"),
    ("Michael", "Mike"), ("Jennifer", "Jen"), ("Christopher", "Chris"), ("Daniel", "Dan"),
    ("Margaret", "Maggie"), ("Alexander", "Alex"), ("Jonathan", "Jon"), ("Samantha", "Sam"),
    ("Nicholas", "Nick"), ("Rebecca", "Becky"), ("Matthew", "Matt"), ("Patricia", "Trish"),
    ("Anthony", "Tony"), ("Victoria", "Vicky"), ("Benjamin", "Ben"), ("Theodore", "Ted"),
    ("Olivia", None), ("Liam", None), ("Emma", None), ("Noah", None), ("Ava", None),
    ("Lucas", None), ("Mia", None), ("Ethan", None), ("Sophie", None), ("Owen", None),
    ("Chloé", None), ("Zoë", None), ("François", None), ("José", None), ("Andrée", None),
    ("Renée", None), ("Hélène", None), ("Jérôme", None), ("Siobhan", None), ("Priya", None),
    ("Arjun", None), ("Wei", None), ("Mei", None), ("Hiroshi", None), ("Yuki", None),
    ("Fatima", None), ("Omar", None), ("Amara", None), ("Kwame", None), ("Ingrid", None),
    ("Søren", None), ("Mateo", None), ("Lucía", None), ("Harpreet", None), ("Gurpreet", None),
    ("Nadia", None), ("Dmitri", None), ("Anya", None), ("Aroha", None), ("Camille", None),
]

LAST_NAMES = [
    "Smith", "Brown", "Tremblay", "Martin", "Roy", "Gagnon", "Lee", "Wilson", "Johnson",
    "MacDonald", "Taylor", "Campbell", "Anderson", "Leblanc", "Côté", "Bouchard", "Gauthier",
    "Morin", "Lavoie", "Fortin", "Singh", "Patel", "Nguyen", "Chen", "Wong", "Kim", "Li",
    "Zhang", "Kaur", "Gill", "Sandhu", "O'Brien", "O'Neil", "McAllister", "Fraser", "Stewart",
    "Reid", "Murray", "Desjardins", "Bélanger", "Pelletier", "Lévesque", "Ouellet", "Sørensen",
    "Müller", "Novak", "Kowalski", "Rossi", "García", "Haddad", "Okafor", "Mensah", "Ivanova",
]

EMAIL_DOMAINS = ["example.com", "example.net", "example.org", "mail.example.ca", "inbox.example"]

# city, province code, country, timezone, postal/zip prefixes, phone area codes, weight, store code
CITIES = [
    ("Vancouver", "BC", "CA", "America/Vancouver", ["V6B", "V5K", "V6K", "V5N"], ["604", "778"], 18, "VAN"),
    ("Victoria", "BC", "CA", "America/Vancouver", ["V8W", "V8V"], ["250"], 5, "VIC"),
    ("Kelowna", "BC", "CA", "America/Vancouver", ["V1Y"], ["250"], 3, "KEL"),
    ("Surrey", "BC", "CA", "America/Vancouver", ["V3T", "V4N"], ["604", "778"], 6, "SUR"),
    ("Calgary", "AB", "CA", "America/Edmonton", ["T2P", "T3A"], ["403", "587"], 8, "CGY"),
    ("Edmonton", "AB", "CA", "America/Edmonton", ["T5J", "T6E"], ["780"], 6, "EDM"),
    ("Saskatoon", "SK", "CA", "America/Regina", ["S7K"], ["306"], 2, "SKT"),
    ("Winnipeg", "MB", "CA", "America/Winnipeg", ["R3C"], ["204"], 3, "WPG"),
    ("Toronto", "ON", "CA", "America/Toronto", ["M5V", "M4C", "M6H"], ["416", "647"], 18, "TOR"),
    ("Ottawa", "ON", "CA", "America/Toronto", ["K1P", "K2P"], ["613"], 5, "OTT"),
    ("Hamilton", "ON", "CA", "America/Toronto", ["L8P"], ["905"], 3, "HAM"),
    ("Montréal", "QC", "CA", "America/Toronto", ["H2X", "H3B", "H2J"], ["514", "438"], 10, "MTL"),
    ("Québec", "QC", "CA", "America/Toronto", ["G1R"], ["418"], 3, "QUE"),
    ("Halifax", "NS", "CA", "America/Halifax", ["B3H"], ["902"], 3, "HFX"),
    ("Seattle", "WA", "US", "America/Los_Angeles", ["98101", "98103"], ["206"], 4, "SEA"),
    ("Portland", "OR", "US", "America/Los_Angeles", ["97201"], ["503"], 2, "PDX"),
    ("Bellingham", "WA", "US", "America/Los_Angeles", ["98225"], ["360"], 1, "BLI"),
]

PROVINCE_VARIANTS = {
    "BC": ["BC", "B.C.", "British Columbia", "bc"],
    "AB": ["AB", "Alta.", "Alberta", "ab"],
    "SK": ["SK", "Sask.", "Saskatchewan"],
    "MB": ["MB", "Man.", "Manitoba"],
    "ON": ["ON", "Ont.", "Ontario", "on"],
    "QC": ["QC", "Que.", "Québec", "Quebec", "PQ"],
    "NS": ["NS", "N.S.", "Nova Scotia"],
    "WA": ["WA", "Wash.", "Washington"],
    "OR": ["OR", "Ore.", "Oregon"],
}

COUNTRY_VARIANTS = {
    "CA": ["CA", "Canada", "CAN", "ca"],
    "US": ["US", "USA", "United States", "U.S."],
}

TAX_RATES = {
    "BC": 0.12, "AB": 0.05, "SK": 0.11, "MB": 0.12, "ON": 0.13,
    "QC": 0.14975, "NS": 0.15, "WA": 0.101, "OR": 0.0,
}

STREETS = ["Main", "Oak", "Maple", "Cedar", "Granville", "Robson", "Yonge", "Queen", "King",
           "Bloor", "Sainte-Catherine", "Saint-Denis", "Jasper", "Portage", "Barrington",
           "Pine", "Elm", "Birch", "Spruce", "Willow", "Lakeshore", "Hastings", "Commercial"]
STREET_SUFFIXES = ["St", "Ave", "Rd", "Blvd", "Dr", "Cres", "Way"]

# department -> category -> (adjectives, nouns, price range CAD, sized?)
CATALOG = {
    "Apparel": {
        "Tops": (["Merino", "Cotton", "Linen", "Performance", "Heritage", "Organic"],
                 ["Tee", "Henley", "Polo", "Hoodie", "Crewneck", "Flannel Shirt"], (19, 99), True),
        "Bottoms": (["Stretch", "Canvas", "Twill", "Trail", "Relaxed", "Slim"],
                    ["Chino", "Jean", "Jogger", "Short", "Cargo Pant"], (39, 129), True),
        "Outerwear": (["Insulated", "Waterproof", "Packable", "Down", "Fleece", "Softshell"],
                      ["Jacket", "Parka", "Vest", "Anorak", "Shell"], (79, 399), True),
    },
    "Footwear": {
        "Boots": (["Leather", "Winter", "Hiking", "Chelsea", "Work"],
                  ["Boot", "Mid Boot", "Duck Boot"], (89, 279), True),
        "Sneakers": (["Court", "Trail", "Knit", "Retro", "Everyday"],
                     ["Sneaker", "Runner", "Slip-On"], (59, 189), True),
    },
    "Home": {
        "Kitchen": (["Cast Iron", "Enamel", "Stoneware", "Bamboo", "Copper"],
                    ["Skillet", "Dutch Oven", "Mug Set", "Cutting Board", "Kettle"], (14, 249), False),
        "Bedding": (["Percale", "Flannel", "Linen", "Wool", "Sateen"],
                    ["Sheet Set", "Duvet Cover", "Throw", "Pillow", "Quilt"], (29, 299), False),
        "Decor": (["Woven", "Ceramic", "Rustic", "Modern", "Handmade"],
                  ["Vase", "Candle", "Basket", "Lantern", "Frame"], (12, 149), False),
    },
    "Outdoor": {
        "Camping": (["Ultralight", "Family", "Backcountry", "Compact", "Rugged"],
                    ["Tent", "Sleeping Bag", "Stove", "Lantern", "Camp Chair"], (25, 599), False),
        "Cycling": (["Commuter", "Gravel", "Reflective", "Pro", "Urban"],
                    ["Helmet", "Bike Light", "Pannier", "Lock", "Jersey"], (19, 249), False),
        "Water Sports": (["Inflatable", "Touring", "Dry", "Quick-Dry", "Coastal"],
                         ["Paddle", "Dry Bag", "PFD", "Rash Guard", "Kayak Seat"], (19, 349), False),
    },
    "Electronics": {
        "Audio": (["Wireless", "Noise-Cancelling", "Rugged", "Studio", "Mini"],
                  ["Headphones", "Earbuds", "Speaker", "Radio"], (29, 399), False),
        "Accessories": (["Solar", "Fast", "Braided", "Magnetic", "Travel"],
                        ["Charger", "Power Bank", "Cable", "Phone Mount", "Adapter"], (9, 129), False),
    },
}

COLORS = ["Navy", "Black", "Grey", "White", "Green", "Red", "Blue", "Beige", "Olive",
          "Burgundy", "Charcoal", "Forest", "Cream"]
COLORS_FR = {"Navy": "Marine", "Black": "Noir", "Grey": "Gris", "White": "Blanc", "Green": "Vert",
             "Red": "Rouge", "Blue": "Bleu", "Beige": "Beige", "Olive": "Olive",
             "Burgundy": "Bordeaux", "Charcoal": "Charbon", "Forest": "Forêt", "Cream": "Crème"}
SIZES = ["XS", "S", "M", "L", "XL", "XXL"]

SUPPLIER_PREFIXES = ["Northwind", "Cascade", "Prairie", "Maritime", "Boreal", "Summit", "Fraser",
                     "Laurentian", "Pacific", "Granite", "Juniper", "Tamarack", "Kootenay", "Algonquin"]
SUPPLIER_SUFFIXES = ["Textiles", "Outfitters Supply", "Goods Ltd.", "Manufacturing", "Trading Co.",
                     "Imports", "Housewares", "Gear Inc."]

CARRIERS_CA = ["Canada Post", "Purolator", "UPS", "FedEx"]
CARRIERS_US = ["USPS", "UPS", "FedEx"]
CARRIER_VARIANTS = {
    "Canada Post": ["Canada Post", "CANADA POST", "CanadaPost", "Postes Canada"],
    "Purolator": ["Purolator", "PUROLATOR", "Purolator Inc"],
    "UPS": ["UPS", "ups", "U.P.S."],
    "FedEx": ["FedEx", "FEDEX", "Fed Ex"],
    "USPS": ["USPS", "usps", "US Postal Service"],
}

RETURN_REASONS = ["too_small", "too_large", "damaged", "not_as_described", "changed_mind",
                  "arrived_late", "wrong_item"]

DEVICES = [("desktop", "Windows", "Chrome"), ("desktop", "macOS", "Safari"),
           ("desktop", "Windows", "Edge"), ("mobile", "iOS", "Safari"),
           ("mobile", "Android", "Chrome"), ("tablet", "iPadOS", "Safari")]
UTM_SOURCES = [("google", "cpc"), ("newsletter", "email"), ("instagram", "social"),
               ("facebook", "social"), ("partner_blog", "referral")]
BOT_AGENTS = ["Mozilla/5.0 (compatible; bingbot/2.0)", "HeadlessChrome/120.0",
              "python-requests/2.31", "Mozilla/5.0 (compatible; PriceWatchCrawler/1.4)"]
