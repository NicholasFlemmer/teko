"""One-time migration: normalize all coach phone numbers in Firestore.

Usage:
    cd backend
    python -m scripts.normalize_phones
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.firebase_service import FirebaseService
from utils.phone import normalize_sa_phone

def main():
    FirebaseService.initialize()
    coaches = FirebaseService.get_all_coaches()
    updated = 0

    for coach in coaches:
        raw = coach.get('phone_number', '')
        normalized = normalize_sa_phone(raw)
        if normalized and normalized != raw:
            FirebaseService.update_coach(coach['id'], {'phone_number': normalized})
            name = coach.get('name', coach['id'])
            print(f"  {name}: '{raw}' -> '{normalized}'")
            updated += 1

    print(f"\nDone. Updated {updated} of {len(coaches)} coaches.")

if __name__ == '__main__':
    main()
