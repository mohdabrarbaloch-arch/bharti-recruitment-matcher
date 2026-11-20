"""API tests: auth, jobs, candidates, ranking, and the status-code matrix.

The status matrix is the part worth reading. Every one of these is a decision
about what the API tells a caller, and several of them are deliberately
unhelpful to an attacker.
"""

from __future__ import annotations

from tests.conftest import STRONG_RESUME, WEAK_RESUME


class TestHealth:
    def test_health_returns_ok(self, client) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_security_headers_are_present(self, client) -> None:
        response = client.get("/api/health")
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in response.headers


class TestAuth:
    def test_register_returns_token(self, client) -> None:
        response = client.post(
            "/api/auth/register",
            json={
                "email": "new@example.com",
                "full_name": "New User",
                "password": "a-good-password",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["access_token"]
        assert body["user"]["email"] == "new@example.com"

    def test_duplicate_email_is_409(self, client, auth_headers) -> None:
        response = client.post(
            "/api/auth/register",
            json={
                "email": "recruiter@example.com",
                "full_name": "Someone Else",
                "password": "another-password",
            },
        )
        assert response.status_code == 409

    def test_short_password_is_422(self, client) -> None:
        response = client.post(
            "/api/auth/register",
            json={"email": "x@example.com", "full_name": "X Y", "password": "short"},
        )
        assert response.status_code == 422

    def test_login_succeeds(self, client, auth_headers) -> None:
        response = client.post(
            "/api/auth/login",
            json={"email": "recruiter@example.com", "password": "test-password-123"},
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    def test_wrong_password_is_401(self, client, auth_headers) -> None:
        response = client.post(
            "/api/auth/login",
            json={"email": "recruiter@example.com", "password": "wrong-password"},
        )
        assert response.status_code == 401

    def test_unknown_user_gives_the_same_message_as_wrong_password(
        self, client
    ) -> None:
        """Account enumeration: the two failures must be indistinguishable."""
        unknown = client.post(
            "/api/auth/login",
            json={"email": "nobody@example.com", "password": "whatever-123"},
        )
        assert unknown.status_code == 401
        assert unknown.json()["detail"] == "Incorrect email or password"

    def test_me_requires_a_token(self, client) -> None:
        assert client.get("/api/auth/me").status_code == 401

    def test_me_with_bad_token_is_401(self, client) -> None:
        response = client.get(
            "/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
        )
        assert response.status_code == 401

    def test_me_returns_the_user(self, client, auth_headers) -> None:
        response = client.get("/api/auth/me", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["email"] == "recruiter@example.com"


class TestJobs:
    def test_create_job(self, client, auth_headers) -> None:
        response = client.post(
            "/api/jobs",
            headers=auth_headers,
            json={"title": "Backend Engineer", "required_skills": ["Python", "Docker"]},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["title"] == "Backend Engineer"
        # Skills are normalised to canonical names on the way in.
        assert body["required_skills"] == ["python", "docker"]

    def test_create_job_requires_auth(self, client) -> None:
        response = client.post("/api/jobs", json={"title": "Backend Engineer"})
        assert response.status_code == 401

    def test_empty_title_is_422(self, client, auth_headers) -> None:
        response = client.post("/api/jobs", headers=auth_headers, json={"title": "x"})
        assert response.status_code == 422

    def test_negative_years_is_422(self, client, auth_headers) -> None:
        response = client.post(
            "/api/jobs",
            headers=auth_headers,
            json={"title": "Backend Engineer", "min_years": -5},
        )
        assert response.status_code == 422

    def test_unknown_job_is_404(self, client, auth_headers) -> None:
        response = client.get("/api/jobs/9999", headers=auth_headers)
        assert response.status_code == 404

    def test_list_jobs(self, client, auth_headers, sample_job) -> None:
        response = client.get("/api/jobs", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_update_job(self, client, auth_headers, sample_job) -> None:
        response = client.patch(
            f"/api/jobs/{sample_job['id']}",
            headers=auth_headers,
            json={"title": "Staff Backend Engineer"},
        )
        assert response.status_code == 200
        assert response.json()["title"] == "Staff Backend Engineer"

    def test_delete_job_is_204(self, client, auth_headers, sample_job) -> None:
        response = client.delete(f"/api/jobs/{sample_job['id']}", headers=auth_headers)
        assert response.status_code == 204
        assert (
            client.get(
                f"/api/jobs/{sample_job['id']}", headers=auth_headers
            ).status_code
            == 404
        )

    def test_another_users_job_is_404_not_403(
        self, client, auth_headers, sample_job
    ) -> None:
        """A 403 would confirm the job exists, which leaks another tenant's
        pipeline shape."""
        other = client.post(
            "/api/auth/register",
            json={
                "email": "other@example.com",
                "full_name": "Other Recruiter",
                "password": "other-password-123",
            },
        )
        other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
        response = client.get(f"/api/jobs/{sample_job['id']}", headers=other_headers)
        assert response.status_code == 404


class TestCandidates:
    def test_add_candidate_parses_the_resume(
        self, client, auth_headers, sample_job
    ) -> None:
        response = client.post(
            f"/api/jobs/{sample_job['id']}/candidates",
            headers=auth_headers,
            json={"resume_text": STRONG_RESUME},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["email"] == "ayesha@example.com"
        assert "python" in body["skills"]
        assert body["years_experience"] > 5

    def test_duplicate_candidate_is_409(self, client, auth_headers, sample_job) -> None:
        payload = {"resume_text": STRONG_RESUME}
        first = client.post(
            f"/api/jobs/{sample_job['id']}/candidates",
            headers=auth_headers,
            json=payload,
        )
        assert first.status_code == 201
        second = client.post(
            f"/api/jobs/{sample_job['id']}/candidates",
            headers=auth_headers,
            json=payload,
        )
        assert second.status_code == 409

    def test_resume_without_email_is_422(
        self, client, auth_headers, sample_job
    ) -> None:
        response = client.post(
            f"/api/jobs/{sample_job['id']}/candidates",
            headers=auth_headers,
            json={
                "resume_text": (
                    "Ali Khan\nPython developer with no contact details at all."
                )
            },
        )
        assert response.status_code == 422

    def test_short_resume_is_422(self, client, auth_headers, sample_job) -> None:
        response = client.post(
            f"/api/jobs/{sample_job['id']}/candidates",
            headers=auth_headers,
            json={"resume_text": "too short"},
        )
        assert response.status_code == 422

    def test_status_update(self, client, auth_headers, sample_job) -> None:
        created = client.post(
            f"/api/jobs/{sample_job['id']}/candidates",
            headers=auth_headers,
            json={"resume_text": STRONG_RESUME},
        ).json()
        response = client.patch(
            f"/api/jobs/{sample_job['id']}/candidates/{created['id']}",
            headers=auth_headers,
            json={"status": "shortlisted"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "shortlisted"

    def test_invalid_status_is_422(self, client, auth_headers, sample_job) -> None:
        created = client.post(
            f"/api/jobs/{sample_job['id']}/candidates",
            headers=auth_headers,
            json={"resume_text": STRONG_RESUME},
        ).json()
        response = client.patch(
            f"/api/jobs/{sample_job['id']}/candidates/{created['id']}",
            headers=auth_headers,
            json={"status": "maybe"},
        )
        assert response.status_code == 422


class TestRanking:
    def test_strong_candidate_outranks_weak(
        self, client, auth_headers, sample_job
    ) -> None:
        for resume in (WEAK_RESUME, STRONG_RESUME):
            client.post(
                f"/api/jobs/{sample_job['id']}/candidates",
                headers=auth_headers,
                json={"resume_text": resume},
            )

        response = client.get(
            f"/api/jobs/{sample_job['id']}/ranked", headers=auth_headers
        )
        assert response.status_code == 200
        ranked = response.json()
        assert len(ranked) == 2
        assert ranked[0]["candidate"]["email"] == "ayesha@example.com"
        assert ranked[0]["match"]["total"] > ranked[1]["match"]["total"]

    def test_ranked_includes_the_breakdown(
        self, client, auth_headers, sample_job
    ) -> None:
        client.post(
            f"/api/jobs/{sample_job['id']}/candidates",
            headers=auth_headers,
            json={"resume_text": STRONG_RESUME},
        )
        ranked = client.get(
            f"/api/jobs/{sample_job['id']}/ranked", headers=auth_headers
        ).json()
        match = ranked[0]["match"]
        assert len(match["components"]) == 5
        assert all("reason" in c for c in match["components"])
        assert "verdict" in match
        assert "confidence" in match

    def test_min_score_filter(self, client, auth_headers, sample_job) -> None:
        for resume in (WEAK_RESUME, STRONG_RESUME):
            client.post(
                f"/api/jobs/{sample_job['id']}/candidates",
                headers=auth_headers,
                json={"resume_text": resume},
            )
        response = client.get(
            f"/api/jobs/{sample_job['id']}/ranked?min_score=90", headers=auth_headers
        )
        assert response.status_code == 200
        assert all(r["match"]["total"] >= 90 for r in response.json())

    def test_changing_requirements_rescores(
        self, client, auth_headers, sample_job
    ) -> None:
        """A leaderboard that describes a job that no longer exists is worse
        than no leaderboard."""
        client.post(
            f"/api/jobs/{sample_job['id']}/candidates",
            headers=auth_headers,
            json={"resume_text": STRONG_RESUME},
        )
        before = client.get(
            f"/api/jobs/{sample_job['id']}/ranked", headers=auth_headers
        ).json()[0]["match"]["total"]

        client.patch(
            f"/api/jobs/{sample_job['id']}",
            headers=auth_headers,
            json={
                "required_skills": [
                    "python",
                    "postgres",
                    "docker",
                    "kubernetes",
                    "terraform",
                ]
            },
        )
        after = client.get(
            f"/api/jobs/{sample_job['id']}/ranked", headers=auth_headers
        ).json()[0]["match"]["total"]

        assert after < before


class TestMeta:
    def test_skills_endpoint_requires_auth(self, client) -> None:
        assert client.get("/api/skills").status_code == 401

    def test_skills_endpoint_returns_taxonomy(self, client, auth_headers) -> None:
        response = client.get("/api/skills", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()) > 50

    def test_skills_search(self, client, auth_headers) -> None:
        response = client.get("/api/skills?q=react", headers=auth_headers)
        assert response.status_code == 200
        names = [s["name"] for s in response.json()]
        assert "react" in names

    def test_admin_stats_requires_admin(self, client, auth_headers) -> None:
        """The first user is admin in tests (FIRST_USER_IS_ADMIN=true), so a
        second user is the one that must be refused."""
        other = client.post(
            "/api/auth/register",
            json={
                "email": "plain@example.com",
                "full_name": "Plain Recruiter",
                "password": "plain-password-123",
            },
        )
        headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
        assert client.get("/api/admin/stats", headers=headers).status_code == 403

    def test_admin_stats_works_for_admin(self, client, auth_headers) -> None:
        response = client.get("/api/admin/stats", headers=auth_headers)
        assert response.status_code == 200
        assert "users" in response.json()
