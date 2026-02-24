"""
Systematic review PostgreSQL helper service.

This provides a higher-level API for operations on the Systematic Review table so
that routers (e.g. backend/api/sr/router.py) can call compact helper functions instead
of implementing DB logic inline.

All blocking DB operations are synchronous and intended to be run with
`fastapi.concurrency.run_in_threadpool` when called from async routes.
"""
from typing import Any, Dict, Optional, List
import logging
import uuid
import json
from datetime import datetime

from fastapi import HTTPException, status

from .postgres_auth import postgres_server
from ..core.config import settings

logger = logging.getLogger(__name__)


class SRDBService:
    def __init__(self):
        # Service is stateless; connection strings passed per-call
        pass

    def ensure_table_exists(self) -> None:
        """
        Ensure the systematic_reviews table exists in PostgreSQL.
        Creates the table if it doesn't exist.
        Call this from FastAPI startup.
        """
        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            
            create_table_sql = """
                CREATE TABLE IF NOT EXISTS systematic_reviews (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    owner_id TEXT NOT NULL,
                    owner_email TEXT,
                    users JSONB DEFAULT '[]'::jsonb,
                    visible BOOLEAN DEFAULT TRUE,
                    criteria JSONB,
                    criteria_yaml TEXT,
                    criteria_parsed JSONB,
                    screening_db JSONB,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
                )
            """
            cur.execute(create_table_sql)
            conn.commit()
                
            logger.info("Ensured systematic_reviews table exists")
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception(f"Failed to ensure systematic_reviews table exists: {e}")
            raise
        finally:
            if conn:
                pass

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
                                'For articles that satisfy the below criteria in XML tags <{key}></{key}> we answer with "{key}":\n\n<{key}>\n{info}\n</{key}>'.format(
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
                                'For articles that satisfy the below criteria in XML tags <{key}></{key}> we answer with "{key}":\n\n<{key}>\n{info}\n</{key}>'.format(
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

    def create_systematic_review(
        self,
        name: str,
        description: Optional[str],
        criteria_str: Optional[str],
        criteria_obj: Optional[Dict[str, Any]],
        owner_id: str,
        owner_email: Optional[str],
    ) -> Dict[str, Any]:
        """
        Create a new SR document and insert into the table. Returns the created document.
        """

        sr_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        criteria_parsed = self.build_criteria_parsed(criteria_obj)

        # Build users array with owner_email
        users_list = [owner_email] if owner_email else []

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            
            insert_sql = """
                INSERT INTO systematic_reviews 
                (id, name, description, owner_id, owner_email, users, visible, 
                 criteria, criteria_yaml, criteria_parsed, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            cur.execute(insert_sql, (
                sr_id,
                name.strip(),
                description,
                owner_id,
                owner_email,
                json.dumps(users_list),
                True,
                json.dumps(criteria_obj) if criteria_obj else None,
                criteria_str,
                json.dumps(criteria_parsed),
                now,
                now
            ))
            
            conn.commit()
            
            # Fetch the created record
            cur.execute("SELECT * FROM systematic_reviews WHERE id = %s", (sr_id,))
            row = cur.fetchone()
            cols = [desc[0] for desc in cur.description]
            sr_doc = {cols[i]: row[i] for i in range(len(cols))}
            
            # Parse JSON fields and convert timestamps
            if sr_doc.get('users') and isinstance(sr_doc['users'], str):
                sr_doc['users'] = json.loads(sr_doc['users'])
            if sr_doc.get('criteria') and isinstance(sr_doc['criteria'], str):
                sr_doc['criteria'] = json.loads(sr_doc['criteria'])
            if sr_doc.get('criteria_parsed') and isinstance(sr_doc['criteria_parsed'], str):
                sr_doc['criteria_parsed'] = json.loads(sr_doc['criteria_parsed'])
            # Convert datetime objects to ISO strings
            from datetime import datetime as dt
            if sr_doc.get('created_at') and isinstance(sr_doc['created_at'], dt):
                sr_doc['created_at'] = sr_doc['created_at'].isoformat()
            if sr_doc.get('updated_at') and isinstance(sr_doc['updated_at'], dt):
                sr_doc['updated_at'] = sr_doc['updated_at'].isoformat()
            

            
            return sr_doc
            
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception(f"Failed to insert SR document: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create systematic review: {e}")
        finally:
            if conn:
                pass

    def add_user(self, sr_id: str, target_user_id: str, requester_id: str) -> Dict[str, Any]:
        """
        Add a user id to the SR's users list. Enforces that the SR exists and is visible;
        requester must be a member or owner.
        Returns a dict with update result metadata.
        """
  

        sr = self.get_systematic_review(sr_id)
        if not sr or not sr.get("visible", True):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

        # Check permission
        has_perm = self.user_has_sr_permission(sr_id, requester_id)
        if not has_perm:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this systematic review")

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            
            # Get current users array
            cur.execute("SELECT users FROM systematic_reviews WHERE id = %s", (sr_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")
            
            users = row[0] if row[0] else []
            if isinstance(users, str):
                users = json.loads(users)
            
            # Add user if not already present
            if target_user_id not in users:
                users.append(target_user_id)
            
            # Update
            now = datetime.utcnow().isoformat()
            cur.execute(
                "UPDATE systematic_reviews SET users = %s, updated_at = %s WHERE id = %s",
                (json.dumps(users), now, sr_id)
            )
            modified_count = cur.rowcount
            conn.commit()
            

            
            return {"matched_count": 1, "modified_count": modified_count, "added_user_id": target_user_id}
            
        except HTTPException:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception(f"Failed to add user to SR: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to add user: {e}")
        finally:
            if conn:
                pass

    def remove_user(self, sr_id: str, target_user_id: str, requester_id: str) -> Dict[str, Any]:
        """
        Remove a user id from the SR's users list. Owner cannot be removed.
        Enforces requester permissions (must be a member or owner).
        """
        

        sr = self.get_systematic_review(sr_id)
        if not sr or not sr.get("visible", True):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

        # Check permission
        has_perm = self.user_has_sr_permission(sr_id, requester_id)
        if not has_perm:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this systematic review")

        if target_user_id == sr.get("owner_id"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the owner from the systematic review")

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            
            # Get current users array
            cur.execute("SELECT users FROM systematic_reviews WHERE id = %s", (sr_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")
            
            users = row[0] if row[0] else []
            if isinstance(users, str):
                users = json.loads(users)
            
            # Remove user if present
            if target_user_id in users:
                users.remove(target_user_id)
            
            # Update
            now = datetime.utcnow().isoformat()
            cur.execute(
                "UPDATE systematic_reviews SET users = %s, updated_at = %s WHERE id = %s",
                (json.dumps(users), now, sr_id)
            )
            modified_count = cur.rowcount
            conn.commit()
            

            
            return {"matched_count": 1, "modified_count": modified_count, "removed_user_id": target_user_id}
            
        except HTTPException:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception(f"Failed to remove user from SR: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to remove user: {e}")
        finally:
            if conn:
                pass

    def user_has_sr_permission(self, sr_id: str, user_id: str) -> bool:
        """
        Check whether the given user_id is a member (in 'users') or the owner of the SR.
        Returns True if the SR exists and the user is present in the SR's users list or is the owner.
        Note: this check deliberately ignores the SR's 'visible' flag so membership checks
        work regardless of whether the SR is hidden/soft-deleted.
        """
        

        doc = self.get_systematic_review(sr_id, ignore_visibility=True)
        if not doc:
            return False

        users = doc.get("users", [])
        if user_id in users or user_id == doc.get("owner_id"):
            return True
        return False

    def update_criteria(self, sr_id: str, criteria_obj: Dict[str, Any], criteria_str: str, requester_id: str) -> Dict[str, Any]:
        """
        Update the criteria fields (criteria, criteria_yaml, criteria_parsed, updated_at).
        The requester must be a member or owner.
        Returns the updated SR document.
        """
        

        sr = self.get_systematic_review(sr_id)
        if not sr or not sr.get("visible", True):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

        # Check permission
        has_perm = self.user_has_sr_permission(sr_id, requester_id)
        if not has_perm:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this systematic review")

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            
            updated_at = datetime.utcnow().isoformat()
            criteria_parsed = self.build_criteria_parsed(criteria_obj)
            
            update_sql = """
                UPDATE systematic_reviews 
                SET criteria = %s, criteria_yaml = %s, criteria_parsed = %s, updated_at = %s
                WHERE id = %s
            """
            
            cur.execute(update_sql, (
                json.dumps(criteria_obj),
                criteria_str,
                json.dumps(criteria_parsed),
                updated_at,
                sr_id
            ))
            
            if cur.rowcount == 0:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found during update")
            
            conn.commit()
            

            
            # Return fresh doc
            doc = self.get_systematic_review(sr_id)
            return doc
            
        except HTTPException:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            raise
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception(f"Failed to update SR criteria: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update criteria: {e}")
        finally:
            if conn:
                pass

    def list_systematic_reviews_for_user(self, user_email: str) -> List[Dict[str, Any]]:
        """
        Return all SR documents where the user is a member (regardless of visible flag).
        """
        

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            
            # Query using jsonb operator to check if user_email is in users array
            query = """
                SELECT * FROM systematic_reviews 
                WHERE users @> %s::jsonb
                ORDER BY created_at DESC
            """
            
            cur.execute(query, (json.dumps([user_email]),))
            rows = cur.fetchall()
            cols = [desc[0] for desc in cur.description]
            
            results = []
            for row in rows:
                doc = {cols[i]: row[i] for i in range(len(cols))}
                
                # Parse JSON fields and convert timestamps
                if doc.get('users') and isinstance(doc['users'], str):
                    doc['users'] = json.loads(doc['users'])
                if doc.get('criteria') and isinstance(doc['criteria'], str):
                    doc['criteria'] = json.loads(doc['criteria'])
                if doc.get('criteria_parsed') and isinstance(doc['criteria_parsed'], str):
                    doc['criteria_parsed'] = json.loads(doc['criteria_parsed'])
                # Convert datetime objects to ISO strings
                from datetime import datetime as dt
                if doc.get('created_at') and isinstance(doc['created_at'], dt):
                    doc['created_at'] = doc['created_at'].isoformat()
                if doc.get('updated_at') and isinstance(doc['updated_at'], dt):
                    doc['updated_at'] = doc['updated_at'].isoformat()
                
                results.append(doc)
            

            
            return results
            
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception(f"Failed to list SRs for user: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to list systematic reviews: {e}")
        finally:
            if conn:
                pass

    def get_systematic_review(self, sr_id: str, ignore_visibility: bool = False) -> Optional[Dict[str, Any]]:
        """
        Return SR document by id. Returns None if not found.
        If ignore_visibility is False, only returns visible SRs.
        """
        

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            
            if ignore_visibility:
                query = "SELECT * FROM systematic_reviews WHERE id = %s"
            else:
                query = "SELECT * FROM systematic_reviews WHERE id = %s AND visible = TRUE"
            
            cur.execute(query, (sr_id,))
            row = cur.fetchone()
            
            if not row:
                return None
            
            cols = [desc[0] for desc in cur.description]
            doc = {cols[i]: row[i] for i in range(len(cols))}
            
            # Parse JSON fields and convert timestamps
            if doc.get('users') and isinstance(doc['users'], str):
                doc['users'] = json.loads(doc['users'])
            if doc.get('criteria') and isinstance(doc['criteria'], str):
                doc['criteria'] = json.loads(doc['criteria'])
            if doc.get('criteria_parsed') and isinstance(doc['criteria_parsed'], str):
                doc['criteria_parsed'] = json.loads(doc['criteria_parsed'])
            # Convert datetime objects to ISO strings
            from datetime import datetime as dt
            if doc.get('created_at') and isinstance(doc['created_at'], dt):
                doc['created_at'] = doc['created_at'].isoformat()
            if doc.get('updated_at') and isinstance(doc['updated_at'], dt):
                doc['updated_at'] = doc['updated_at'].isoformat()
            

            
            return doc
            
        except Exception as e:
            # IMPORTANT: do not swallow DB errors as "not found".
            # Roll back so this connection isn't poisoned for subsequent requests.
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception(f"Failed to get SR: {e}")
            raise
        finally:
            if conn:
                pass

    def set_visibility(self, sr_id: str, visible: bool, requester_id: str) -> Dict[str, Any]:
        """
        Set the visible flag on the SR. Only owner is allowed to change visibility.
        Returns update metadata.
        """
        

        sr = self.get_systematic_review(sr_id, ignore_visibility=True)
        if not sr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

        if requester_id != sr.get("owner_id"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner may change visibility of this systematic review")

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            
            updated_at = datetime.utcnow().isoformat()
            cur.execute(
                "UPDATE systematic_reviews SET visible = %s, updated_at = %s WHERE id = %s",
                (bool(visible), updated_at, sr_id)
            )
            modified_count = cur.rowcount
            conn.commit()
            

            
            return {"matched_count": 1, "modified_count": modified_count, "visible": visible}
            
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception(f"Failed to set visibility on SR: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to set visibility: {e}")
        finally:
            if conn:
               pass

    def soft_delete_systematic_review(self, sr_id: str, requester_id: str) -> Dict[str, Any]:
        """
        Soft-delete (set visible=False). Only owner may delete.
        """
        return self.set_visibility(sr_id, False, requester_id)

    def undelete_systematic_review(self, sr_id: str, requester_id: str) -> Dict[str, Any]:
        """
        Undelete (set visible=True). Only owner may undelete.
        """
        return self.set_visibility(sr_id, True, requester_id)

    def hard_delete_systematic_review(self, sr_id: str, requester_id: str) -> Dict[str, Any]:
        """
        Permanently remove the SR document. Only owner may hard delete.
        Returns deletion metadata (deleted_count).
        """
        

        sr = self.get_systematic_review(sr_id, ignore_visibility=True)
        if not sr:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Systematic review not found")

        if requester_id != sr.get("owner_id"):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner may hard-delete this systematic review")

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            
            cur.execute("DELETE FROM systematic_reviews WHERE id = %s", (sr_id,))
            deleted_count = cur.rowcount
            conn.commit()

            return {"deleted_count": deleted_count}
            
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception(f"Failed to hard-delete SR: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to hard-delete systematic review: {e}")
        finally:
            if conn:
                pass


    def update_screening_db_info(self, sr_id: str, screening_db: Dict[str, Any]) -> None:
        """
        Update the screening_db field in the SR document with screening database metadata.
        """
        

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            
            updated_at = datetime.utcnow().isoformat()
            cur.execute(
                "UPDATE systematic_reviews SET screening_db = %s, updated_at = %s WHERE id = %s",
                (json.dumps(screening_db), updated_at, sr_id)
            )
            conn.commit()
            

            
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception(f"Failed to update screening DB info: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to update screening DB info: {e}")
        finally:
            if conn:
                pass

    def clear_screening_db_info(self, sr_id: str) -> None:
        """
        Remove the screening_db field from the SR document.
        """
        

        conn = None
        try:
            conn = postgres_server.conn
            cur = conn.cursor()
            
            updated_at = datetime.utcnow().isoformat()
            cur.execute(
                "UPDATE systematic_reviews SET screening_db = NULL, updated_at = %s WHERE id = %s",
                (updated_at, sr_id)
            )
            conn.commit()
            

            
        except Exception as e:
            try:
                if conn:
                    conn.rollback()
            except Exception:
                pass
            logger.exception(f"Failed to clear screening DB info: {e}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to clear screening DB info: {e}")
        finally:
            if conn:
                pass


# module-level instance
srdb_service = SRDBService()
