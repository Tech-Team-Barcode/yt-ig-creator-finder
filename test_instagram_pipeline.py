import unittest

from hashtag_planner import evaluate_hashtag_quality
from ig_scraper import apply_local_profile_scoring


class HashtagQualityGateTests(unittest.TestCase):
    def setUp(self):
        self.intent = {
            "niche": "menskincare",
            "gender": "M",
            "language": "kannada",
            "city": None,
            "state": "karnataka",
        }

    def test_rejects_broad_regional_blogger_tags_for_skincare(self):
        for tag in ("#kannadablogger", "#karnatakablogger", "#nammabengaluru"):
            result = evaluate_hashtag_quality(tag, self.intent, 50_000)
            self.assertFalse(result["selected"], tag)

    def test_accepts_male_skincare_tags(self):
        for tag in ("#indianmenskincare", "#mensgroomingindia", "#skincareformen"):
            result = evaluate_hashtag_quality(tag, self.intent, 80_000)
            self.assertTrue(result["selected"], tag)
            self.assertGreaterEqual(result["score"], 45)


class LocalProfileScoringTests(unittest.TestCase):
    def test_valid_indian_grooming_creator_scores_high(self):
        creator = {
            "platform": "instagram",
            "username": "rahul_grooms",
            "full_name": "Rahul Sharma",
            "bio": "Men's grooming creator | Mumbai | DM for collab",
            "caption": "Honest Minimalist sunscreen review for men",
            "recent_captions": "My skincare routine with cleanser, serum and SPF",
            "hashtags": ["menskincare", "skincareformen", "mensgroomingindia"],
            "source_hashtags": ["indianmenskincare"],
            "followers": 18000,
            "posts_count": 45,
            "enriched": True,
            "is_private": False,
            "business_category": "Digital creator",
        }
        scored = apply_local_profile_scoring(
            creator, "menskincare", 5000, 50000, "M", ["india"]
        )
        self.assertEqual(scored["match_status"], "high")
        self.assertGreaterEqual(scored["niche_confidence"], 55)
        self.assertGreaterEqual(scored["india_confidence"], 25)

    def test_food_business_using_bad_hashtag_is_rejected(self):
        creator = {
            "platform": "instagram",
            "username": "chefchandraskitchen",
            "full_name": "Umesh Chandra",
            "bio": "Real Recipe For Business Enquiries",
            "caption": "#skincareformen #mensgrooming",
            "recent_captions": "Paneer recipe and kitchen tips",
            "hashtags": ["skincareformen", "mensgrooming", "food", "recipe"],
            "source_hashtags": ["skincareformen"],
            "followers": 6866,
            "posts_count": 90,
            "enriched": True,
            "is_private": False,
            "business_category": "Food & Beverage",
        }
        scored = apply_local_profile_scoring(
            creator, "menskincare", 5000, 50000, "M", ["india"]
        )
        self.assertEqual(scored["match_status"], "rejected")
        self.assertIn("business", scored["reject_reason"])

    def test_follower_range_is_strict_after_enrichment(self):
        creator = {
            "platform": "instagram",
            "username": "small_groomer",
            "full_name": "Aman",
            "bio": "Men's grooming creator India",
            "caption": "skincare routine for men",
            "recent_captions": "sunscreen review",
            "hashtags": ["menskincare"],
            "source_hashtags": ["indianmenskincare"],
            "followers": 4999,
            "posts_count": 30,
            "enriched": True,
            "is_private": False,
            "business_category": "Digital creator",
        }
        scored = apply_local_profile_scoring(
            creator, "menskincare", 5000, 50000, "M", ["india"]
        )
        self.assertEqual(scored["match_status"], "rejected")
        self.assertIn("below minimum", scored["reject_reason"])


if __name__ == "__main__":
    unittest.main()

