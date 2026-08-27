"""Safeguarding detection keyword list, from the client's safeguarding
policy. Pure data -- no matching logic lives here (see
services/safeguarding_service.py for that) so this list can be edited by
someone without touching detection code.

Structured by category. The five categories are fixed by the client's
policy; do not rename or add to them without checking the policy
document first.

Every term is matched case-insensitively, on whole-word boundaries, and
tolerant of surrounding punctuation -- see safeguarding_service.py for
the matching implementation. This module only holds the raw phrases.
"""

SAFEGUARDING_KEYWORDS = {
    'physical_abuse': [
        'hit me',
        'hits me',
        'beat me',
        'beats me',
        'punched me',
        'kicked me',
        'hurt me',
        'hurts me',
        'slapped me',
        'burned me',
        'choked me',
        'threw me',
        'gave me a hiff',
        'klapped me',
        'hit me at home',
        'hits me at home',
        'he hits me',
        'she hits me',
        'they hit me',
        'my dad hits me',
        'my mom hits me',
        'my mum hits me',
        'my uncle hit me',
        'beats me at home',
    ],
    'sexual_abuse': [
        'touched me',
        'touches me',
        'made me touch',
        'private parts',
        'took my clothes',
        'made me undress',
        'showed me his',
        'sent me a picture of his',
        'raped',
        'molested',
    ],
    'grooming': [
        'our secret',
        "don't tell anyone",
        'dont tell anyone',
        'keep it between us',
        'meet me alone',
        'come to my house',
        "don't tell your mom",
        'dont tell your mum',
        'special friend',
        'delete these messages',
        "promise you won't tell",
    ],
    'neglect': [
        'no food at home',
        'nothing to eat',
        "haven't eaten",
        'no one is home',
        'nowhere to sleep',
        'no one looks after me',
        'no one takes care of me',
        'sleeping outside',
    ],
    'emotional_abuse': [
        'they bully me',
        'being bullied',
        'they laugh at me every',
        'calls me worthless',
        "says I'm useless",
        "tells me I'm stupid",
        'scared to go home',
        'scared of him',
        'scared of her',
        'afraid to go home',
        'no one loves me',
    ],
}
