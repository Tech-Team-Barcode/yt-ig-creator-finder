import asyncio
import unittest
from unittest.mock import patch

from hashtag_planner import evaluate_hashtag_quality
from ig_scraper import (
    _figue_profile_to_creator,
    apply_instagram_graph_gate,
    _related_usernames,
    apply_local_profile_scoring,
    instagram_seeds_from_youtube,
    normalize_instagram_username,
    run_ig_related_search_from_youtube,
)


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


class YouTubeSeededInstagramDiscoveryTests(unittest.TestCase):
    def test_normalizes_instagram_urls_handles_and_rejects_post_paths(self):
        self.assertEqual(normalize_instagram_username("https://www.instagram.com/Rahul.Grooms/?hl=en"), "rahul.grooms")
        self.assertEqual(normalize_instagram_username("@Aman_Creates"), "aman_creates")
        self.assertEqual(normalize_instagram_username("plain.handle"), "plain.handle")
        self.assertEqual(normalize_instagram_username("https://instagram.com/reel/ABC123"), "")

    def test_collects_only_unique_instagram_seeds_from_youtube_results(self):
        creators = [
            {"platform": "youtube", "channel_name": "A", "instagram_url": "https://www.instagram.com/creator.one/"},
            {"platform": "youtube", "channel_name": "B", "instagram_url": "@Creator.One"},
            {"platform": "youtube", "channel_name": "C", "instagram_handle": "creator_two"},
            {"platform": "instagram", "username": "not_a_youtube_seed"},
        ]
        seeds = instagram_seeds_from_youtube(creators)
        self.assertEqual([row["username"] for row in seeds], ["creator.one", "creator_two"])
        self.assertEqual(seeds[0]["source_youtube_channel"], "A")

    def test_maps_figue_profile_and_related_profiles_to_table_contract(self):
        raw = {
            "username": "creator.one",
            "full_name": "Creator One",
            "biography": "Mumbai skincare creator | collabs: hello@creatorstudio.in",
            "followersCount": 24000,
            "postsCount": 80,
            "business_phone_number": "+91 90000 00000",
            "category_name": "Digital creator",
            "profile_pic_url_hd": "https://cdn.example/avatar.jpg",
            "external_url": "https://creator.example",
            "latestPosts": [{
                "url": "https://www.instagram.com/p/abc/",
                "caption": "Routine #skincare",
                "hashtags": ["skincare"],
                "video_url": "https://cdn.example/reel.mp4",
            }],
            "edge_related_profiles": [{"username": "related.one"}, "https://instagram.com/related.two/"],
        }
        related = _related_usernames(raw)
        creator = _figue_profile_to_creator(
            raw,
            {
                "username": "creator.one",
                "seed_username": "creator.one",
                "source_username": "creator.one",
                "discovery_depth": 0,
                "source_youtube_channel": "Creator on YouTube",
            },
        )
        self.assertEqual(related, ["related.one", "related.two"])
        self.assertEqual(creator["profile_url"], "https://www.instagram.com/creator.one/")
        self.assertEqual(creator["followers"], 24000)
        self.assertEqual(creator["sample_post_url"], "https://www.instagram.com/p/abc/")
        self.assertEqual(creator["latest_reel_url"], "https://cdn.example/reel.mp4")
        self.assertEqual(creator["email"], "hello@creatorstudio.in")
        self.assertEqual(creator["ig_discovery_source"], "youtube_seed")
        self.assertEqual(creator["source_youtube_channel"], "Creator on YouTube")

    def test_expands_two_related_profile_hops_from_youtube_seed(self):
        raw_by_username = {
            "seed.creator": {"username": "seed.creator", "followersCount": 10000, "edge_related_profiles": ["hop.one"]},
            "hop.one": {"username": "hop.one", "followersCount": 12000, "edge_related_profiles": ["hop.two"]},
            "hop.two": {"username": "hop.two", "followersCount": 14000, "edge_related_profiles": []},
        }

        async def fake_scrape(_session, _keys, targets, _log):
            return [(raw_by_username[target["username"]], target) for target in targets]

        debug = {}
        with patch("ig_scraper._scrape_figue_profiles", new=fake_scrape):
            results = asyncio.run(run_ig_related_search_from_youtube(
                yt_creators=[{"platform": "youtube", "channel_name": "Seed", "instagram_url": "@seed.creator"}],
                profile_api_keys=["token"],
                min_followers=0,
                max_followers=50000,
                location_hints=[],
                related_depth=2,
                include_rejected=True,
                debug_state=debug,
            ))

        by_username = {row["username"]: row for row in results}
        self.assertEqual(set(by_username), {"seed.creator", "hop.one", "hop.two"})
        self.assertEqual(by_username["hop.one"]["ig_discovery_depth"], 1)
        self.assertEqual(by_username["hop.two"]["ig_discovery_depth"], 2)
        self.assertEqual(debug["fetched_profiles"], 3)

    def test_graph_gate_hides_foreign_or_weak_location_rows(self):
        creators = [
            {
                "username": "india.creator",
                "match_status": "high",
                "local_match_score": 80,
                "india_confidence": 35,
                "followers": 10000,
                "bio": "Mumbai skincare creator",
            },
            {
                "username": "foreign.creator",
                "match_status": "high",
                "local_match_score": 90,
                "india_confidence": 0,
                "followers": 90000,
                "bio": "China fashion creator",
            },
        ]
        surfaced = apply_instagram_graph_gate(creators, ["india"], include_rejected=False)
        self.assertEqual([row["username"] for row in surfaced], ["india.creator"])
        self.assertEqual(creators[1]["reject_reason"], "missing India/location evidence")


if __name__ == "__main__":
    unittest.main()

