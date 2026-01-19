"""
Systematic review Mongo/Cosmos helper service.

This provides a higher-level API for operations on the Systematic Review collection so
that routers (e.g. backend/api/sr/router.py) can call compact helper functions instead
of implementing DB logic inline.

The service adapts to using either the Cosmos helper (cosmodb_service) or the local
MongoDB motor-based mongodb_service instance depending on what's available.
"""
from typing import Any, Dict, Optional, List
from types import SimpleNamespace
import logging
import uuid
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient  # type: ignore
from ..core.config import settings

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


class SRDBService:
    def __init__(self):

        uri = settings.MONGODB_URI
        db_name = settings.MONGODB_DB
        coll_name = settings.MONGODB_SYSTEMATIC_REVIEW_COLLECTION


        # Initialize motor async client (used at runtime). If pymongo created the
        # collection above, motor will see it; otherwise motor is still initialized
        # and the app can operate (collection may be created lazily).
        try:
            self.client = AsyncIOMotorClient(uri)
            self.db = self.client[db_name]
            self.collection = self.db[coll_name]
        except Exception as e:
            logger.warning("Failed to initialize AsyncIOMotorClient: %s", e)
            self.client = None
            self.db = None
            self.collection = None

    async def ensure_collection_exists(self) -> None:
        """
        Ensure the systematic review collection exists using motor (async).
        Call this from FastAPI startup to create the collection if missing.
        """
        if self.db is None:
            logger.warning("No DB client available to ensure collection exists")
            return
        try:
            coll_name = settings.MONGODB_SYSTEMATIC_REVIEW_COLLECTION
            existing = await self.db.list_collection_names()
            if coll_name not in existing:
                await self.db.create_collection(coll_name)
                logger.info("Created missing collection %s", coll_name)
            # Refresh collection reference
            self.collection = self.db[coll_name]
        except Exception as e:
            logger.exception("Failed to ensure systematic review collection exists: %s", e)

    def ensure_db_available(self) -> None:
        """
        Raise an HTTPException (503) if the MongoDB collection is not available.
        Routers call this to provide consistent error messages when Mongo is not configured.
        """
        if self.collection is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="MongoDB client not configured. Set MONGODB_URI / AZURE_COSMOS_MONGODB_URI environment variable.",
            )

    def _get_collection(self):
        return self.collection

    def build_criteria_parsed(self, criteria_obj: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Port of the _build_criteria_parsed helper - returns a mapping containing
        'l1', 'l2', 'parameters' structured metadata for the UI and screening logic.
        """
        parsed: Dict[str, Any] = {"l1": {}, "l2": {}, "parameters": {}}
        if not criteria_obj or not isinstance(criteria_obj, dict):
            return parsed

        # include list (columns)
        include = criteria_obj.get("include", [])
        if isinstance(include, list):
            parsed["l1"]["include"] = include

        # l1 criteria (title/abstract)
        crit = criteria_obj.get("criteria", {})
        qlist: List[str] = []
        possible: List[List[str]] = []
        addinfos: List[str] = []
        if isinstance(crit, dict):
            for q, answers in crit.items():
                qlist.append(q)
                if isinstance(answers, dict):
                    possible.append([k for k in answers.keys()])
                    addinfos.append(
                        "\n\n".join(
                            [
                                "For articles that satisfy the below criteria in XML tags <{key}></{key}> we answer with “{key}”:\n\n<{key}>\n{info}\n</{key}>".format(
                                    key=k, info=v
                                )
                                for k, v in answers.items()
                            ]
                        )
                    )
                else:
                    possible.append([])
                    addinfos.append("")
        parsed["l1"].update({"questions": qlist, "possible_answers": possible, "additional_infos": addinfos})

        # l2 criteria (fulltext)
        l2 = criteria_obj.get("l2_criteria", {})
        l2_q: List[str] = []
        l2_possible: List[List[str]] = []
        l2_addinfos: List[str] = []
        if isinstance(l2, dict):
            for q, answers in l2.items():
                l2_q.append(q)
                if isinstance(answers, dict):
                    l2_possible.append([k for k in answers.keys()])
                    l2_addinfos.append(
                        "\n\n".join(
                            [
                                "For articles that satisfy the below criteria in XML tags <{key}></{key}> we answer with “{key}”:\n\n<{key}>\n{info}\n</{key}>".format(
                                    key=k, info=v
                                )
                                for k, v in answers.items()
                            ]
                        )
                    )
                else:
                    l2_possible.append([])
                    l2_addinfos.append("")
        parsed["l2"].update({"questions": l2_q, "possible_answers": l2_possible, "additional_infos": l2_addinfos})

        # parameters
        params = criteria_obj.get("parameters", {})
        categories: List[str] = []
        possible_params: List[List[str]] = []
        descriptions: List[List[str]] = []
        if isinstance(params, dict):
            for cat, param_map in params.items():
                categories.append(cat)
                if isinstance(param_map, dict):
                    possible_params.append([k for k in param_map.keys()])
                    descriptions.append(
                        [
                            "Parameter {key} are described as <desc>{info}</desc>.".format(key=k, info=v)
                            for k, v in param_map.items()
                        ]
                    )
                else:
                    possible_params.append([])
                    descriptions.append([])
        parsed["parameters"].update({"categories": categories, "possible_parameters": possible_params, "descriptions": descriptions})

        return parsed

    async def create_systematic_review(
        self,
        name: str,
        description: Optional[str],
        criteria_str: Optional[str],
        criteria_obj: Optional[Dict[str, Any]],
        owner_id: str,
        owner_email: Optional[str],
    ) -> Dict[str, Any]:
        """
        Create a new SR document and insert into the collection. Returns the created document.
        """
        coll = self._get_collection()
        if coll is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Systematic review DB not configured")

        sr_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        criteria_parsed = self.build_criteria_parsed(criteria_obj)

        sr_doc = {
            "_id": sr_id,
            "name": name.strip(),
            "description": description,
            "owner_id": owner_id,
            "owner_email": owner_email,
            "users": [owner_email],
            "visible": True,
            "criteria": criteria_obj,
            "criteria_yaml": criteria_str,
            "criteria_parsed": criteria_parsed,
            "created_at": now,
            "updated_at": now,
        }

        try:
            await coll.insert_one(sr_doc)
        except Exception as e:
            logger.exception("Failed to insert SR document: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create systematic review: {e}")

        return sr_doc

    async def add_user(self, sr_id: str, target_user_id: str, requester_id: str) -> Dict[str, Any]:
        """
        Add a user id to the SR's users list. Enforces that the SR exists and is visible;
        requester must be a member or owner.
        Returns a dict with update result metadata.
        """
        coll = self._get_collection()
        if coll is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Systematic review DB not configured")

        sr = await coll.find_one({"_id": sr_id})
        if not sr or not sr.get("visible", True):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

        # Use helper to check membership/ownership (ignores visibility)
        has_perm = await self.user_has_sr_permission(sr_id, requester_id)
        if not has_perm:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this systematic review")

        try:
            result = await coll.update_one(
                {"_id": sr_id},
                {"$addToSet": {"users": target_user_id}, "$set": {"updated_at": datetime.utcnow().isoformat()}},
            )
        except Exception as e:
            logger.exception("Failed to add user to SR: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to add user: {e}")

        return {"matched_count": getattr(result, "matched_count", None), "modified_count": getattr(result, "modified_count", None), "added_user_id": target_user_id}

    async def remove_user(self, sr_id: str, target_user_id: str, requester_id: str) -> Dict[str, Any]:
        """
        Remove a user id from the SR's users list. Owner cannot be removed.
        Enforces requester permissions (must be a member or owner).
        """
        coll = self._get_collection()
        if coll is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Systematic review DB not configured")

        sr = await coll.find_one({"_id": sr_id})
        if not sr or not sr.get("visible", True):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

        # Use helper to check membership/ownership (ignores visibility)
        has_perm = await self.user_has_sr_permission(sr_id, requester_id)
        if not has_perm:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this systematic review")

        if target_user_id == sr.get("owner_id"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the owner from the systematic review")

        try:
            result = await coll.update_one(
                {"_id": sr_id},
                {"$pull": {"users": target_user_id}, "$set": {"updated_at": datetime.utcnow().isoformat()}},
            )
        except Exception as e:
            logger.exception("Failed to remove user from SR: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to remove user: {e}")

        return {"matched_count": getattr(result, "matched_count", None), "modified_count": getattr(result, "modified_count", None), "removed_user_id": target_user_id}

    async def user_has_sr_permission(self, sr_id: str, user_id: str) -> bool:
        """
        Check whether the given user_id is a member (in 'users') or the owner of the SR.
        Returns True if the SR exists and the user is present in the SR's users list or is the owner.
        Note: this check deliberately ignores the SR's 'visible' flag so membership checks
        work regardless of whether the SR is hidden/soft-deleted.
        """
        coll = self._get_collection()
        if coll is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Systematic review DB not configured")

        doc = await coll.find_one({"_id": sr_id})
        if not doc:
            return False

        if user_id in doc.get("users", []) or user_id == doc.get("owner_id"):
            return True
        return False

    async def update_criteria(self, sr_id: str, criteria_obj: Dict[str, Any], criteria_str: str, requester_id: str) -> Dict[str, Any]:
        """
        Update the criteria fields (criteria, criteria_yaml, criteria_parsed, updated_at).
        The requester must be a member or owner.
        Returns the updated SR document.
        """
        coll = self._get_collection()
        if coll is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Systematic review DB not configured")

        sr = await coll.find_one({"_id": sr_id})
        if not sr or not sr.get("visible", True):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

        # Use helper to check membership/ownership (ignores visibility)
        has_perm = await self.user_has_sr_permission(sr_id, requester_id)
        if not has_perm:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this systematic review")

        try:
            updated_at = datetime.utcnow().isoformat()
            criteria_parsed = self.build_criteria_parsed(criteria_obj)
            result = await coll.update_one(
                {"_id": sr_id},
                {"$set": {"criteria": criteria_obj, "criteria_yaml": criteria_str, "criteria_parsed": criteria_parsed, "updated_at": updated_at}},
            )
            if getattr(result, "matched_count", 0) == 0:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found during update")
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("Failed to update SR criteria: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update criteria: {e}")

        # return fresh doc
        doc = await coll.find_one({"_id": sr_id})
        return doc

    async def list_systematic_reviews_for_user(self, user_email: str) -> List[Dict[str, Any]]:
        """
        Return all SR documents where the user is a member (regardless of visible flag).
        """
        coll = self._get_collection()
        if coll is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Systematic review DB not configured")

        results: List[Dict[str, Any]] = []
        cursor = coll.find({"users": user_email})
        try:
            async for doc in cursor:
                results.append(doc)
        except Exception as e:
            logger.exception("Failed to list SRs for user: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list systematic reviews: {e}")

        return results

    async def get_systematic_review(self, sr_id: str) -> Optional[Dict[str, Any]]:
        """
        Return SR document by id (regardless of permission). Returns None if not found.
        """
        coll = self._get_collection()
        if coll is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Systematic review DB not configured")

        doc = await coll.find_one({"_id": sr_id})
        return doc

    async def set_visibility(self, sr_id: str, visible: bool, requester_id: str) -> Dict[str, Any]:
        """
        Set the visible flag on the SR. Only owner is allowed to change visibility.
        Returns update metadata.
        """
        coll = self._get_collection()
        if coll is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Systematic review DB not configured")

        sr = await coll.find_one({"_id": sr_id})
        if not sr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

        if requester_id != sr.get("owner_id"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner may change visibility of this systematic review")

        try:
            updated_at = datetime.utcnow().isoformat()
            result = await coll.update_one({"_id": sr_id}, {"$set": {"visible": bool(visible), "updated_at": updated_at}})
        except Exception as e:
            logger.exception("Failed to set visibility on SR: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to set visibility: {e}")

        return {"matched_count": getattr(result, "matched_count", None), "modified_count": getattr(result, "modified_count", None), "visible": visible}

    async def soft_delete_systematic_review(self, sr_id: str, requester_id: str) -> Dict[str, Any]:
        """
        Soft-delete (set visible=False). Only owner may delete.
        """
        return await self.set_visibility(sr_id, False, requester_id)

    async def undelete_systematic_review(self, sr_id: str, requester_id: str) -> Dict[str, Any]:
        """
        Undelete (set visible=True). Only owner may undelete.
        """
        return await self.set_visibility(sr_id, True, requester_id)

    async def hard_delete_systematic_review(self, sr_id: str, requester_id: str) -> Dict[str, Any]:
        """
        Permanently remove the SR document. Only owner may hard delete.
        Returns deletion metadata (deleted_count, matched_count).
        """
        coll = self._get_collection()
        if coll is None:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Systematic review DB not configured")

        sr = await coll.find_one({"_id": sr_id})
        if not sr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

        if requester_id != sr.get("owner_id"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner may hard-delete this systematic review")

        try:
            result = await coll.delete_one({"_id": sr_id})
            # cosmodb_service returns UpdateResult-like object; mongodb delete_one returns DeleteResult
            deleted_count = getattr(result, "deleted_count", getattr(result, "deleted_count", None))
            # Some proxies return an UpdateResult with deleted_count or methods; best-effort
            if deleted_count is None:
                # Try deleted_count or deleted_count property fallbacks
                deleted_count = getattr(result, "deleted_count", 0)
        except Exception as e:
            logger.exception("Failed to hard-delete SR: %s", e)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to hard-delete systematic review: {e}")

        return {"deleted_count": deleted_count}

# module-level instance
srdb_service = SRDBService()
