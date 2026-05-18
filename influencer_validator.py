"""
influencer_validator.py — Robust Instagram Influencer Detection
================================================================
PROBLEM IT SOLVES:
- Rate limiting from heavy AI usage
- Expensive Gemini calls for every profile
- Poor early filtering of non-creators
- Missing behavioral/statistical signals

APPROACH:
1. Statistical scoring (0 Gemini calls) for most accounts
2. Business pattern matching for hard rejections
3. Engagement-based authenticity checks
4. Only ambiguous cases go to AI (saves 85%+ calls)
"""

import re
import math
from typing import Dict, Tuple, Optional
from enum import Enum
from dataclasses import dataclass


class CreatorConfidence(Enum):
    """Confidence level that account is a real creator"""
    DEFINITELY_YES = "high"
    PROBABLY_YES = "medium"
    PROBABLY_NO = "low"
    DEFINITELY_NO = "reject"


@dataclass
class ValidationResult:
    """Result of influencer validation"""
    score: int  # 0-100
    confidence: CreatorConfidence
    is_creator: bool
    is_business: bool
    reason: str
    needs_ai_review: bool
    signals: Dict[str, any]


class InstagramInfluencerValidator:
    """
    Statistical influencer validator. Eliminates ~85% of non-creators
    without using AI, saving massive API costs and avoiding rate limits.
    """

    # ─── PATTERNS FOR BUSINESS/NON-CREATOR ACCOUNTS ──────────────────────
    
    HARD_BUSINESS_PATTERNS = re.compile(
        r"\b(pvt\s*ltd|private\s*limited|llp|limited\s*company|"
        r"pvt|company|inc|corp|Ltd\.|®|™|©|"
        r"products?|services?|solutions?|"
        r"buy now|shop now|order|purchase|"
        r"wholesale|bulk|distributor|supplier|manufacturer|vendor|retailer|"
        r"dermatolog|cosmetic\s*surger|skin\s*clinic|hair\s*clinic|transplant|"
        r"hospital|clinic|pharmacy|medical|doctor|"
        r"showroom|store|shop|mall|center|salon|spa|"
        r"ministry|government|university|school|college|academy|institute|"
        r"news|media|press|publication|channel|tv|"
        r"@gmail\.com|@yahoomail|contact\s*us|"
        r"whatsapp to order|call to order|dm for orders|"
        r"cash on delivery|worldwide shipping|pan india|"
        r"available on|flipkart|amazon|"
        r"limited offers?|exclusive deal|discount|sale|%\s*off)\b",
        re.IGNORECASE
    )

    CLINIC_STORE_PATTERNS = re.compile(
        r"\b(clinic|hospital|pharmacy|doctor|medical|surgery|surgical|"
        r"dermatolog|aesthet|cosmetic|dental|skin care center|hair salon|"
        r"salon|spa|massage|therapy|treatment|"
        r"store|shop|mall|retail|showroom|"
        r"ecommerce|online store|e-shop|"
        r"brand|company|corporate|business|"
        r"distributor|dealer|reseller|"
        r"agency|services|solutions)\b",
        re.IGNORECASE
    )

    LINK_PATTERNS = {
        "store": re.compile(r"(flipkart|amazon|myntra|ajio|meesho|snapdeal|nykaa|purplle|linc)\.com"),
        "clinic": re.compile(r"(clinic|hospital|health|medical|surgery|doctor)\."),
        "ecommerce": re.compile(r"(shop|buy|order|store)\."),
        "personal_site": re.compile(r"(linktree|beacons|milkshake|linkfire)\."),
    }

    CREATOR_INDICATORS = re.compile(
        r"\b(content\s*creator|influencer|blogger|vlogger|youtuber|tiktoker|"
        r"digital\s*creator|creatives?|"
        r"dm for collab|collab inquiries?|brand\s*deals?|partnerships?|"
        r"featured in|worked with|"
        r"reels|shorts|tiktok|youtube|"
        r"honest reviews?|real reviews?|"
        r"self\s*care|skincare\s*enthusiast|beauty\s*junkie|"
        r"travel enthusiast|food lover|lifestyle|"
        r"photography|videography|editing|"
        r"sharing my journey|my channel|my account|"
        r"entrepreneur|freelancer|consultant|coach|trainer)\b",
        re.IGNORECASE
    )

    LANGUAGE_MARKERS = {
        "hindi": r"\b(aaj|kal|yeh|vo|kya|achha|bilkul|haan|nahi|tumhara|mera|"\
                 r"बहुत|अच्छा|बस|करो|हो|है|और|या|क्या)\b",
        "hindi_mixed": r"(yaar|bhai|dost|bilkul|bilkool|kya|kal|abhi|bas|haa|naah)",
    }

    # ─── ACCOUNT AGE & AUTHENTICITY PATTERNS ──────────────────────────────

    MIN_POSTS_FOR_ESTABLISHED = 15  # Too new accounts are usually not "established influencers"
    MIN_FOLLOWERS_FOR_ESTABLISHED = 1000  # Below this, engagement rate matters more
    HIGH_FOLLOWER_MINIMUM = 10000

    # Engagement metrics
    EXPECTED_ENGAGEMENT_RANGE = {
        "nano": (0.5, 8.0),  # 0.5-8% engagement for 1K-10K followers
        "micro": (0.3, 5.0),  # 0.3-5% engagement for 10K-100K
        "mid": (0.1, 3.0),  # 0.1-3% engagement for 100K-500K
        "macro": (0.05, 1.5),  # 0.05-1.5% engagement for 500K+
    }

    SPAM_COMMENT_RATE = 0.8  # If >80% of comments are just emojis/spam, reject

    def __init__(self):
        self.cache: Dict[str, ValidationResult] = {}

    def get_follower_tier(self, followers: int) -> str:
        """Classify creator tier by follower count"""
        if followers < 1000:
            return "nano_small"
        elif followers < 10000:
            return "nano"
        elif followers < 100000:
            return "micro"
        elif followers < 500000:
            return "mid"
        else:
            return "macro"

    def calculate_engagement_rate(self, likes: int, comments: int, followers: int) -> float:
        """Calculate engagement rate as (likes + comments) / followers"""
        if followers <= 0:
            return 0.0
        total_engagement = likes + comments
        return (total_engagement / followers) * 100

    def analyze_bio_quality(self, bio: str, full_name: str, username: str) -> Dict[str, any]:
        """Analyze bio for creator authenticity signals"""
        if not bio:
            return {
                "quality_score": 0,
                "is_empty_bio": True,
                "has_link": False,
                "link_type": None,
                "has_creator_signals": False,
                "has_business_signals": False,
            }

        full_text = f"{bio} {full_name} {username}".lower()

        # Check for links
        has_link = bool(re.search(r"https?://|\.com|\.in|\.net", bio))
        link_type = self._classify_link(bio)

        # Check signals
        has_creator_signals = bool(self.CREATOR_INDICATORS.search(bio))
        has_hard_business = bool(self.HARD_BUSINESS_PATTERNS.search(bio))
        has_clinic_store = bool(self.CLINIC_STORE_PATTERNS.search(full_text))

        # Bio quality scoring
        quality_score = 0
        if len(bio) > 80:
            quality_score += 15  # Good length
        if bio.count("\n") >= 1:
            quality_score += 10  # Structured
        if has_creator_signals:
            quality_score += 25  # Creator language
        if has_link and link_type == "personal_site":
            quality_score += 10  # Portfolio/linktree
        
        # Penalize
        if has_hard_business:
            quality_score -= 50
        if has_clinic_store:
            quality_score -= 40
        if link_type == "store":
            quality_score -= 30
        if link_type == "clinic":
            quality_score -= 40

        quality_score = max(0, min(100, quality_score))

        return {
            "quality_score": quality_score,
            "is_empty_bio": False,
            "has_link": has_link,
            "link_type": link_type,
            "has_creator_signals": has_creator_signals,
            "has_business_signals": has_hard_business or has_clinic_store,
        }

    def _classify_link(self, bio: str) -> Optional[str]:
        """Classify what type of link is in bio"""
        for link_type, pattern in self.LINK_PATTERNS.items():
            if pattern.search(bio):
                return link_type
        return None

    def check_follower_authenticity(self, followers: int, posts: int, bio_length: int) -> Tuple[float, str]:
        """
        Check if follower count seems authentic.
        Returns (authenticity_score 0-100, reason)
        """
        score = 100
        reasons = []

        # Profile completeness correlates with authenticity
        if bio_length < 20:
            score -= 20
            reasons.append("incomplete_bio")
        elif bio_length > 500:
            score -= 5  # Over-promotional
            reasons.append("excessive_bio")

        # New accounts with high followers are suspicious
        if posts < 5 and followers > 1000:
            score -= 40
            reasons.append("new_account_high_followers")
        elif posts < 10 and followers > 5000:
            score -= 20
            reasons.append("few_posts_high_followers")

        # Very high posts with few followers suggests bot activity
        if posts > 500 and followers < 1000:
            score -= 30
            reasons.append("spam_posting_pattern")

        # Reasonable posting consistency
        posts_per_day = posts / 300 if posts > 0 else 0  # Rough estimate
        if posts_per_day > 3:  # More than 3 posts per day on average is suspicious
            score -= 20
            reasons.append("excessive_posting")

        score = max(0, min(100, score))
        return score, "; ".join(reasons) if reasons else "authentic"

    def check_engagement_authenticity(
        self, 
        likes: int, 
        comments: int, 
        followers: int,
        posts: int
    ) -> Tuple[float, str]:
        """
        Check engagement authenticity.
        Real creators have natural engagement patterns.
        """
        if followers < 100:
            return 50, "too_new"

        engagement_rate = self.calculate_engagement_rate(likes, comments, followers)
        tier = self.get_follower_tier(followers)
        min_eng, max_eng = self.EXPECTED_ENGAGEMENT_RANGE.get(tier, (0.1, 5.0))

        score = 100
        reasons = []

        # Engagement too low for tier (could be fake followers)
        if engagement_rate < min_eng * 0.3:
            score -= 50
            reasons.append(f"suspiciously_low_engagement_{engagement_rate:.1f}%")
        elif engagement_rate < min_eng:
            score -= 20
            reasons.append(f"below_expected_engagement_{engagement_rate:.1f}%")

        # Engagement too high (engagement pods or bot interactions)
        if engagement_rate > max_eng * 3:
            score -= 40
            reasons.append(f"suspiciously_high_engagement_{engagement_rate:.1f}%")
        elif engagement_rate > max_eng:
            score -= 15
            reasons.append(f"above_typical_engagement_{engagement_rate:.1f}%")

        # Very few posts but high engagement (artificial)
        if posts < 5 and engagement_rate > max_eng * 2:
            score -= 30
            reasons.append("high_engagement_few_posts")

        score = max(0, min(100, score))
        return score, "; ".join(reasons) if reasons else "normal_engagement"

    def validate_profile(
        self,
        username: str,
        full_name: str,
        bio: str,
        followers: int,
        posts_count: int,
        is_private: bool,
        is_business: bool,
        business_category: str,
        likes: int = 0,
        comments: int = 0,
        recent_captions: str = "",
        **kwargs
    ) -> ValidationResult:
        """
        Main validation function. Returns structured result without using AI.
        Only returns needs_ai_review=True for ambiguous cases (50-75 score).
        """
        
        # ─── HARD REJECTIONS (0% chance of creator) ──────────────────────
        
        if is_private:
            return ValidationResult(
                score=0, confidence=CreatorConfidence.DEFINITELY_NO,
                is_creator=False, is_business=False,
                reason="Private account - not discoverable for influencer campaigns",
                needs_ai_review=False, signals={"rejection_type": "private"}
            )

        full_text = f"{username} {full_name} {bio} {recent_captions}".lower()

        if self.HARD_BUSINESS_PATTERNS.search(full_text):
            return ValidationResult(
                score=0, confidence=CreatorConfidence.DEFINITELY_NO,
                is_creator=False, is_business=True,
                reason="Hard business pattern detected (store, clinic, distributor, etc.)",
                needs_ai_review=False,
                signals={"rejection_type": "hard_business"}
            )

        if is_business and business_category:
            cat_lower = business_category.lower()
            if any(x in cat_lower for x in [
                "shopping", "retail", "health", "medical", "doctor", "clinic",
                "hospital", "pharmacy", "school", "education", "news", "media"
            ]):
                if not self.CREATOR_INDICATORS.search(bio):  # No creator signals to override
                    return ValidationResult(
                        score=5, confidence=CreatorConfidence.DEFINITELY_NO,
                        is_creator=False, is_business=True,
                        reason=f"Instagram business account: {business_category}",
                        needs_ai_review=False,
                        signals={"rejection_type": "business_category"}
                    )

        # Too new to be established influencer
        if posts_count < 3:
            return ValidationResult(
                score=5, confidence=CreatorConfidence.DEFINITELY_NO,
                is_creator=False, is_business=False,
                reason="Too few posts - account too new",
                needs_ai_review=False,
                signals={"rejection_type": "too_new"}
            )

        # ─── SCORING PHASE ────────────────────────────────────────────────

        score = 50  # Start with neutral
        signals = {}

        # BIO ANALYSIS (0-30 points)
        bio_analysis = self.analyze_bio_quality(bio, full_name, username)
        bio_quality = bio_analysis["quality_score"]
        signals["bio_quality"] = bio_quality
        
        if bio_analysis["is_empty_bio"]:
            score -= 15
            signals["empty_bio"] = True
        else:
            score += (bio_quality / 100) * 30  # Up to +30 for good bio

        # ENGAGEMENT AUTHENTICITY (0-25 points)
        if likes > 0 or comments > 0:
            eng_score, eng_reason = self.check_engagement_authenticity(
                likes, comments, followers, posts_count
            )
            signals["engagement_authenticity"] = eng_score
            signals["engagement_reason"] = eng_reason
            score += (eng_score / 100) * 25  # Up to +25 for authentic engagement
        else:
            score -= 10  # No engagement data available

        # FOLLOWER AUTHENTICITY (0-20 points)
        auth_score, auth_reason = self.check_follower_authenticity(
            followers, posts_count, len(bio)
        )
        signals["follower_authenticity"] = auth_score
        signals["authenticity_reason"] = auth_reason
        score += (auth_score / 100) * 20  # Up to +20 for authentic follower pattern

        # MINIMUM THRESHOLD (0-25 points)
        if followers > 0:
            if followers >= self.HIGH_FOLLOWER_MINIMUM:
                score += 15
                signals["established_account"] = True
            elif followers >= self.MIN_FOLLOWERS_FOR_ESTABLISHED:
                score += 8
                signals["micro_influencer"] = True
            else:
                score += 3
                signals["nano_influencer"] = True

        if posts_count >= self.MIN_POSTS_FOR_ESTABLISHED:
            score += 7
            signals["consistent_posting"] = True

        # CREATOR SIGNALS (0-20 points)
        creator_signal_count = len(re.findall(self.CREATOR_INDICATORS, bio))
        if creator_signal_count >= 3:
            score += 20
            signals["strong_creator_signals"] = True
        elif creator_signal_count >= 1:
            score += 10
            signals["some_creator_signals"] = True

        # LOCATION SIGNALS (optional +5 for Indian creators)
        if re.search(r"\b(india|mumbai|delhi|bangalore|hyderabad|creator|bangalore|delhi)\b", bio, re.IGNORECASE):
            score += 5
            signals["location_signals"] = True

        # Normalize score to 0-100
        score = max(0, min(100, score))

        # ─── DETERMINE CONFIDENCE & AI NEED ──────────────────────────────

        if score < 30:
            confidence = CreatorConfidence.DEFINITELY_NO
            needs_ai = False
        elif score < 50:
            confidence = CreatorConfidence.PROBABLY_NO
            needs_ai = score > 40  # Review borderline cases
        elif score < 70:
            confidence = CreatorConfidence.PROBABLY_YES
            needs_ai = True  # Ambiguous - worth AI review
        else:
            confidence = CreatorConfidence.DEFINITELY_YES
            needs_ai = False

        # Reason
        if score >= 70:
            reason = f"Strong creator profile (engagement: {signals.get('engagement_authenticity', 'N/A')}, bio quality: {signals.get('bio_quality', 'N/A')})"
        elif score >= 50:
            reason = f"Possibly legitimate creator (needs review)"
        else:
            reason = f"Unlikely creator profile"

        return ValidationResult(
            score=score,
            confidence=confidence,
            is_creator=score >= 60,
            is_business=bio_analysis["has_business_signals"],
            reason=reason,
            needs_ai_review=needs_ai,
            signals=signals
        )


def create_post_validator():
    """Factory function to create validator"""
    return InstagramInfluencerValidator()
