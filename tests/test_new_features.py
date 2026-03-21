"""
Tests for the extended features:
  - Vanity address multi-chain support
  - Memecoin factory multi-chain router
  - Faucet per-chain config
  - AI agent skills multi-framework support
  - Self-trained bot (local ML)
  - Fund tracer forensic logic
  - DEX Bot scoring engine
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Vanity address – multi-chain
# ─────────────────────────────────────────────────────────────────────────────

class TestVanityMultiChain:
    def test_supported_chains_includes_bitcoin_solana_tron(self):
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator
        chains = VanityAddressGenerator.supported_chains()
        assert "bitcoin" in chains
        assert "solana" in chains
        assert "tron" in chains
        assert "ethereum" in chains

    def test_unsupported_chain_raises(self):
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator
        gen = VanityAddressGenerator()
        with pytest.raises(NotImplementedError):
            gen.find(chain="xmr_nonexistent", prefix="abc", workers=1, max_attempts_per_worker=1)

    def test_vanity_result_has_chain_field(self):
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator
        gen = VanityAddressGenerator()
        # Very short prefix so it finds quickly
        result = gen.find(chain="ethereum", prefix="0x", workers=1, max_attempts_per_worker=500)
        assert result is not None
        assert result.chain == "ethereum"

    def test_build_pattern_prefix(self):
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator
        pat = VanityAddressGenerator._build_pattern("0xDEAD", None, None)
        assert pat.startswith("^")
        assert "DEAD" in pat

    def test_build_pattern_suffix(self):
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator
        pat = VanityAddressGenerator._build_pattern(None, "beef", None)
        assert pat.endswith("$")

    def test_build_pattern_regex_passthrough(self):
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator
        pat = VanityAddressGenerator._build_pattern(None, None, r"\d{4}")
        assert pat == r"\d{4}"

    def test_resolve_worker_evm(self):
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator, _evm_worker
        fn, kwargs = VanityAddressGenerator._resolve_worker("bsc")
        assert fn is _evm_worker
        assert kwargs == {}

    def test_resolve_worker_bitcoin(self):
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator, _bitcoin_worker
        fn, kwargs = VanityAddressGenerator._resolve_worker("bitcoin")
        assert fn is _bitcoin_worker
        assert kwargs == {"addr_type": "p2pkh"}

    def test_resolve_worker_bitcoin_segwit(self):
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator, _bitcoin_worker
        fn, kwargs = VanityAddressGenerator._resolve_worker("bitcoin_segwit")
        assert fn is _bitcoin_worker
        assert kwargs["addr_type"] == "p2wpkh"

    def test_resolve_worker_solana(self):
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator, _solana_worker
        fn, kwargs = VanityAddressGenerator._resolve_worker("solana")
        assert fn is _solana_worker

    def test_resolve_worker_tron(self):
        from crypto_toolkit.wallet.vanity_address import VanityAddressGenerator, _tron_worker
        fn, kwargs = VanityAddressGenerator._resolve_worker("tron")
        assert fn is _tron_worker


# ─────────────────────────────────────────────────────────────────────────────
# Memecoin factory – multi-chain router
# ─────────────────────────────────────────────────────────────────────────────

class TestMemecoinMultiChain:
    def test_create_token_unsupported_raises(self):
        from crypto_toolkit.defi.memecoin_factory import create_token
        with pytest.raises(ValueError, match="Unsupported chain"):
            create_token(chain="xmr", name="Test", symbol="TST", private_key="0x" + "aa" * 32)

    def test_create_token_evm_missing_key_raises(self):
        from crypto_toolkit.defi.memecoin_factory import create_token
        with pytest.raises(ValueError, match="private_key"):
            create_token(chain="ethereum", name="Test", symbol="TST", private_key=None)

    def test_solana_token_config_defaults(self):
        from crypto_toolkit.defi.memecoin_factory import SolanaTokenConfig
        cfg = SolanaTokenConfig(name="MooCow", symbol="MOO")
        assert cfg.decimals == 9
        assert cfg.total_supply == 1_000_000_000

    def test_evm_chains_includes_bsc_polygon(self):
        from crypto_toolkit.defi.memecoin_factory import _EVM_CHAINS
        assert "bsc" in _EVM_CHAINS
        assert "polygon" in _EVM_CHAINS
        assert "avalanche" in _EVM_CHAINS


# ─────────────────────────────────────────────────────────────────────────────
# Faucet – per-chain config
# ─────────────────────────────────────────────────────────────────────────────

class TestFaucetMultiChain:
    def test_chain_configs_present(self):
        from crypto_toolkit.saas.faucet import _CHAIN_CONFIGS
        assert "ethereum" in _CHAIN_CONFIGS
        assert "solana" in _CHAIN_CONFIGS
        assert "bsc" in _CHAIN_CONFIGS
        assert "polygon" in _CHAIN_CONFIGS

    def test_each_chain_has_native_symbol(self):
        from crypto_toolkit.saas.faucet import _CHAIN_CONFIGS
        for chain, cfg in _CHAIN_CONFIGS.items():
            assert cfg.native_symbol, f"Chain '{chain}' missing native_symbol"

    def test_drip_amounts_positive(self):
        from crypto_toolkit.saas.faucet import _CHAIN_CONFIGS
        for chain, cfg in _CHAIN_CONFIGS.items():
            assert cfg.native_drip_amount > 0, f"Chain '{chain}' drip amount must be > 0"

    def test_bnb_drip_more_than_eth_drip(self):
        from crypto_toolkit.saas.faucet import _CHAIN_CONFIGS
        # BNB is cheaper, so faucet should give more
        assert _CHAIN_CONFIGS["bsc"].native_drip_amount > _CHAIN_CONFIGS["ethereum"].native_drip_amount

    @pytest.mark.asyncio
    async def test_unsupported_chain_returns_400(self):
        from fastapi.testclient import TestClient
        from crypto_toolkit.saas.faucet import app
        client = TestClient(app)
        resp = client.post("/drip", json={"address": "0x" + "ab" * 20, "chain": "xmr_fake"})
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_list_chains_endpoint(self):
        from fastapi.testclient import TestClient
        from crypto_toolkit.saas.faucet import app
        client = TestClient(app)
        resp = client.get("/chains")
        assert resp.status_code == 200
        data = resp.json()
        assert "ethereum" in data
        assert "solana" in data


# ─────────────────────────────────────────────────────────────────────────────
# AI agent skills – multi-framework
# ─────────────────────────────────────────────────────────────────────────────

class TestAgentSkillsMultiFramework:
    def test_openai_schema_structure(self):
        from crypto_toolkit.ai.agent_skills import GenerateWalletSkill
        skill = GenerateWalletSkill()
        schema = skill.openai_schema()
        assert schema["type"] == "function"
        assert "function" in schema
        assert schema["function"]["name"] == "generate_wallet"

    def test_anthropic_schema_structure(self):
        from crypto_toolkit.ai.agent_skills import GenerateWalletSkill
        skill = GenerateWalletSkill()
        schema = skill.anthropic_schema()
        assert "name" in schema
        assert "description" in schema
        assert "input_schema" in schema

    def test_mcp_schema_structure(self):
        from crypto_toolkit.ai.agent_skills import GenerateWalletSkill
        skill = GenerateWalletSkill()
        schema = skill.mcp_schema()
        assert "name" in schema
        assert "inputSchema" in schema

    def test_to_dict_structure(self):
        from crypto_toolkit.ai.agent_skills import CheckBalanceSkill
        skill = CheckBalanceSkill()
        d = skill.to_dict()
        assert d["name"] == "check_balance"
        assert "parameters" in d

    def test_get_all_schemas_openai(self):
        from crypto_toolkit.ai.agent_skills import get_all_schemas
        schemas = get_all_schemas("openai")
        assert len(schemas) > 0
        assert all(s["type"] == "function" for s in schemas)

    def test_get_all_schemas_anthropic(self):
        from crypto_toolkit.ai.agent_skills import get_all_schemas
        schemas = get_all_schemas("anthropic")
        assert all("input_schema" in s for s in schemas)

    def test_get_all_schemas_mcp(self):
        from crypto_toolkit.ai.agent_skills import get_all_schemas
        schemas = get_all_schemas("mcp")
        assert all("inputSchema" in s for s in schemas)

    def test_get_all_schemas_unknown_raises(self):
        from crypto_toolkit.ai.agent_skills import get_all_schemas
        with pytest.raises(ValueError):
            get_all_schemas("unknown_framework_xyz")

    def test_tool_registry_has_new_skills(self):
        from crypto_toolkit.ai.agent_skills import TOOL_REGISTRY
        assert "trace_funds" in TOOL_REGISTRY
        assert "dex_bot_analyse" in TOOL_REGISTRY
        assert "find_vanity_address" in TOOL_REGISTRY

    def test_execute_tool_unknown_raises(self):
        from crypto_toolkit.ai.agent_skills import execute_tool
        with pytest.raises(KeyError):
            asyncio.get_event_loop().run_until_complete(
                execute_tool("nonexistent_tool_xyz", {})
            )


# ─────────────────────────────────────────────────────────────────────────────
# Self-trained bot
# ─────────────────────────────────────────────────────────────────────────────

class TestSelfTrainedBot:
    def _make_candles(self, n: int = 150):
        """Generate synthetic OHLCV candles for testing."""
        from crypto_toolkit.trading.ai_trading_bot import OHLCV
        import random
        random.seed(42)
        price = 2000.0
        candles = []
        for i in range(n):
            change = random.uniform(-0.02, 0.02)
            price *= (1 + change)
            candles.append(OHLCV(
                timestamp=1_700_000_000 + i * 3600,
                open=price * 0.999,
                high=price * 1.01,
                low=price * 0.99,
                close=price,
                volume=random.uniform(100, 1000),
            ))
        return candles

    def test_extended_features_columns(self):
        from crypto_toolkit.trading.self_trained_bot import compute_extended_features
        candles = self._make_candles(100)
        df = compute_extended_features(candles)
        assert "ret_1" in df.columns
        assert "vol_5" in df.columns
        assert "sma_cross" in df.columns
        assert "rsi_os" in df.columns

    def test_ensemble_train_predict(self):
        from crypto_toolkit.trading.self_trained_bot import SelfTrainedEnsemble
        candles = self._make_candles(150)
        model = SelfTrainedEnsemble(token_id="test_token")
        model.train(candles)
        signal = model.predict(candles)
        assert signal.action in {"buy", "sell", "hold"}
        assert 0.0 <= signal.confidence <= 1.0
        assert signal.price > 0

    def test_predict_without_train_raises(self):
        from crypto_toolkit.trading.self_trained_bot import SelfTrainedEnsemble
        model = SelfTrainedEnsemble(token_id="untrained")
        candles = self._make_candles(100)
        with pytest.raises(RuntimeError, match="not yet trained"):
            model.predict(candles)

    def test_self_trained_bot_analyse_uses_local_model(self):
        """analyse() should work without any external API call."""
        from crypto_toolkit.trading.self_trained_bot import SelfTrainedBot
        candles = self._make_candles(150)
        bot = SelfTrainedBot(dry_run=True)

        async def _fake_fetch(token_id, days=90, **kw):
            return candles

        with patch("crypto_toolkit.trading.self_trained_bot.fetch_ohlcv", side_effect=_fake_fetch):
            signal = asyncio.get_event_loop().run_until_complete(bot.analyse("ethereum"))
        assert signal.action in {"buy", "sell", "hold"}
        assert signal.token == "ETHEREUM"

    def test_signal_reasoning_mentions_ensemble(self):
        from crypto_toolkit.trading.self_trained_bot import SelfTrainedEnsemble
        candles = self._make_candles(150)
        model = SelfTrainedEnsemble(token_id="eth")
        model.train(candles)
        signal = model.predict(candles)
        assert "Ensemble" in signal.reasoning or "RF" in signal.reasoning


# ─────────────────────────────────────────────────────────────────────────────
# Fund tracer
# ─────────────────────────────────────────────────────────────────────────────

class TestFundTracer:
    def _make_tx(self, from_addr: str, to_addr: str, value_wei: int, ts: int) -> dict:
        return {
            "hash": "0x" + "ab" * 32,
            "from": from_addr,
            "to": to_addr,
            "value": str(value_wei),
            "timeStamp": str(ts),
            "blockNumber": "1000000",
            "gasUsed": "21000",
        }

    def test_label_known_address(self):
        from crypto_toolkit.tracker.fund_tracer import FundTracer, _KNOWN_LABELS
        addr = list(_KNOWN_LABELS.keys())[0]
        assert FundTracer._label(addr) is not None

    def test_label_unknown_address_returns_none(self):
        from crypto_toolkit.tracker.fund_tracer import FundTracer
        assert FundTracer._label("0x" + "ff" * 20) is None

    def test_is_exchange_sink_true_for_binance(self):
        from crypto_toolkit.tracker.fund_tracer import FundTracer
        binance = "0x3f5ce5fbfe3e9af3971dd833d26ba9b5c936f0be"
        assert FundTracer._is_exchange_sink(binance) is True

    def test_is_exchange_sink_false_for_tornado(self):
        from crypto_toolkit.tracker.fund_tracer import FundTracer
        tornado = "0x722122df12d4e14e13ac3b6895a86e84145b6967"
        assert FundTracer._is_exchange_sink(tornado) is False

    def test_risk_flags_mixer_destination(self):
        from crypto_toolkit.tracker.fund_tracer import FundTracer
        tracer = FundTracer()
        tx = {
            "to": "0x722122df12d4e14e13ac3b6895a86e84145b6967",
            "value": str(int(1.0 * 1e18)),
        }
        flags = tracer._risk_flags(tx, 1.0)
        assert "mixer_destination" in flags
        assert "tornado_denomination" in flags

    def test_trace_report_to_dict(self):
        from crypto_toolkit.tracker.fund_tracer import TraceReport, Hop, AddressProfile
        report = TraceReport(seed_address="0xabc", chain="ethereum")
        report.hops.append(Hop(
            hop_number=1, tx_hash="0x1", from_address="0xabc",
            to_address="0xdef", value_eth=1.0, timestamp=1000, block_number=100,
        ))
        d = report.to_dict()
        assert d["seed_address"] == "0xabc"
        assert len(d["hops"]) == 1
        assert d["hops"][0]["value_eth"] == 1.0

    def test_trace_report_to_text(self):
        from crypto_toolkit.tracker.fund_tracer import TraceReport
        report = TraceReport(seed_address="0xabc", chain="ethereum")
        text = report.to_text()
        assert "Fund Trace" in text
        assert "0xabc" in text

    def test_score_address_high_velocity(self):
        from crypto_toolkit.tracker.fund_tracer import FundTracer, AddressProfile
        tracer = FundTracer()
        now = 1_700_000_000
        # 60 transactions within a 60-minute window
        txs = [
            {"from": "0xaaa", "to": "0xbbb", "value": "1000", "timeStamp": str(now + i * 50)}
            for i in range(60)
        ]
        profile = AddressProfile(address="0xaaa")
        score, flags = tracer._score_address("0xaaa", txs, profile)
        assert "high_velocity" in flags

    @pytest.mark.asyncio
    async def test_trace_returns_report_with_no_api(self):
        """Trace should return a valid report even when explorer returns nothing."""
        from crypto_toolkit.tracker.fund_tracer import FundTracer
        tracer = FundTracer()
        # Patch _fetch_txs to return empty (no real API call)
        tracer._fetch_txs = AsyncMock(return_value=[])
        report = await tracer.trace("0x" + "aa" * 20, chain="ethereum", max_depth=1)
        assert report.seed_address == "0x" + "aa" * 20
        assert isinstance(report.hops, list)


# ─────────────────────────────────────────────────────────────────────────────
# DEX Bot
# ─────────────────────────────────────────────────────────────────────────────

class TestDexBot:
    def _make_report(self, **overrides):
        from crypto_toolkit.trading.dex_bot import (
            DexBot, TokenInfo, SocialMetrics, TradingActivityMetrics, RiskMetrics,
        )
        bot = DexBot()
        token = TokenInfo(
            address="0x" + "ab" * 20,
            chain="ethereum",
            name="TestToken",
            symbol="TST",
            price_usd=0.001,
            market_cap_usd=overrides.get("market_cap_usd", 500_000),
            liquidity_usd=overrides.get("liquidity_usd", 50_000),
            volume_24h_usd=overrides.get("volume_24h_usd", 20_000),
            age_days=overrides.get("age_days", 30),
            holder_count=overrides.get("holder_count", 600),
        )
        social = SocialMetrics(
            twitter_followers=overrides.get("twitter_followers", 10_000),
            hype_score=overrides.get("hype_score", 5.0),
            sentiment_score=0.6,
        )
        trading = TradingActivityMetrics(
            bot_tx_pct=overrides.get("bot_tx_pct", 0.2),
            whale_tx_pct=0.15,
            insider_flag=overrides.get("insider_flag", False),
        )
        risk = RiskMetrics(
            rug_risk_score=overrides.get("rug_risk_score", 2.0),
            honeypot_flag=overrides.get("honeypot_flag", False),
            risk_flags=[],
        )
        return bot, token, social, trading, risk

    def test_compute_score_returns_positive(self):
        bot, token, social, trading, risk = self._make_report()
        score, reasons = bot._compute_score(token, social, trading, risk)
        assert score > 0

    def test_honeypot_gives_avoid(self):
        bot, token, social, trading, risk = self._make_report(honeypot_flag=True)
        rec, conf = bot._decide(80.0, risk, trading)
        assert rec == "avoid"
        assert conf > 0.9

    def test_high_rug_risk_gives_avoid(self):
        bot, token, social, trading, risk = self._make_report(rug_risk_score=8.0)
        rec, conf = bot._decide(50.0, risk, trading)
        assert rec == "avoid"

    def test_high_score_gives_buy(self):
        bot, token, social, trading, risk = self._make_report(
            liquidity_usd=200_000,
            market_cap_usd=2_000_000,
            twitter_followers=50_000,
            hype_score=8.0,
            bot_tx_pct=0.1,
            rug_risk_score=1.0,
        )
        score, _ = bot._compute_score(token, social, trading, risk)
        rec, _ = bot._decide(score, risk, trading)
        assert rec in {"buy", "hold"}

    def test_low_liquidity_mentioned_in_reasons(self):
        bot, token, social, trading, risk = self._make_report(liquidity_usd=500)
        score, reasons = bot._compute_score(token, social, trading, risk)
        assert any("liquidity" in r.lower() for r in reasons)

    def test_hype_score_calculation(self):
        from crypto_toolkit.trading.dex_bot import DexBot, SocialMetrics
        metrics = SocialMetrics(
            twitter_followers=50_000,
            reddit_subscribers=20_000,
            reddit_posts_24h=10,
            telegram_members=50_000,
        )
        score = DexBot._compute_hype_score(metrics)
        assert score == pytest.approx(10.0, abs=0.5)

    def test_hype_score_zero_when_no_community(self):
        from crypto_toolkit.trading.dex_bot import DexBot, SocialMetrics
        metrics = SocialMetrics()
        score = DexBot._compute_hype_score(metrics)
        assert score == 0.0

    def test_detect_insider_false_for_small_sample(self):
        from crypto_toolkit.trading.dex_bot import DexBot
        # Less than 20 txns – should return False
        txs = [{"from": "0xaaa", "value": "1000", "timeStamp": str(i)} for i in range(10)]
        assert DexBot._detect_insider(txs) is False

    def test_report_to_dict_keys(self):
        bot, token, social, trading, risk = self._make_report()
        from crypto_toolkit.trading.dex_bot import DexBotReport
        report = DexBotReport(
            token=token, social=social, trading=trading, risk=risk,
            recommendation="buy", confidence=0.75, score=72.0, reasoning=["test"]
        )
        d = report.to_dict()
        assert "token" in d
        assert "social" in d
        assert "risk" in d
        assert d["recommendation"] == "buy"

    def test_report_to_text(self):
        bot, token, social, trading, risk = self._make_report()
        from crypto_toolkit.trading.dex_bot import DexBotReport
        report = DexBotReport(
            token=token, social=social, trading=trading, risk=risk,
            recommendation="hold", confidence=0.5, score=50.0, reasoning=["ok"]
        )
        text = report.to_text()
        assert "TST" in text
        assert "HOLD" in text

    def test_parse_goplus_honeypot(self):
        from crypto_toolkit.trading.dex_bot import DexBot
        bot = DexBot()
        data = {"is_honeypot": "1"}
        risk = bot._parse_goplus(data)
        assert risk.honeypot_flag is True
        assert risk.rug_risk_score >= 9.0
        assert "honeypot" in risk.risk_flags

    def test_parse_goplus_mintable(self):
        from crypto_toolkit.trading.dex_bot import DexBot
        bot = DexBot()
        data = {
            "is_honeypot": "0",
            "is_mintable": "1",
            "lp_is_locked": "1",
            "owner_address": "",
        }
        risk = bot._parse_goplus(data)
        assert "mintable" in risk.risk_flags

    @pytest.mark.asyncio
    async def test_analyse_with_mocked_apis(self):
        """Full analyse() call with all external HTTP mocked."""
        from crypto_toolkit.trading.dex_bot import DexBot, TokenInfo, SocialMetrics, TradingActivityMetrics, RiskMetrics
        bot = DexBot()

        dummy_token = TokenInfo(
            address="0xtest", chain="ethereum", name="Mock", symbol="MCK",
            price_usd=0.001, market_cap_usd=100_000,
            liquidity_usd=20_000, volume_24h_usd=5_000,
            age_days=30, holder_count=300,
        )
        dummy_social = SocialMetrics(hype_score=4.0, sentiment_score=0.5)
        dummy_trading = TradingActivityMetrics(bot_tx_pct=0.3)
        dummy_risk = RiskMetrics(rug_risk_score=3.0)

        bot._fetch_token_info = AsyncMock(return_value=dummy_token)
        bot._fetch_social_metrics = AsyncMock(return_value=dummy_social)
        bot._analyse_trading_activity = AsyncMock(return_value=dummy_trading)
        bot._assess_risk = AsyncMock(return_value=dummy_risk)

        report = await bot.analyse("0xtest", chain="ethereum")
        assert report.recommendation in {"buy", "sell", "avoid", "hold"}
        assert 0.0 <= report.score <= 100.0


# ─────────────────────────────────────────────────────────────────────────────
# AIDexBot
# ─────────────────────────────────────────────────────────────────────────────

class TestAIDexBot:
    """Tests for the locally self-trained AIDexBot variant."""

    def _make_dummy_report(self, **overrides):
        from crypto_toolkit.trading.dex_bot import (
            DexBotReport, TokenInfo, SocialMetrics,
            TradingActivityMetrics, RiskMetrics,
        )
        return DexBotReport(
            token=TokenInfo(
                address="0x" + "ab" * 20, chain="ethereum",
                name="MockToken", symbol="MCK",
                price_usd=0.001,
                market_cap_usd=overrides.get("market_cap_usd", 200_000),
                liquidity_usd=overrides.get("liquidity_usd", 30_000),
                volume_24h_usd=overrides.get("volume_24h_usd", 8_000),
                age_days=overrides.get("age_days", 20),
                holder_count=overrides.get("holder_count", 400),
            ),
            social=SocialMetrics(
                hype_score=overrides.get("hype_score", 5.0),
                sentiment_score=0.55,
            ),
            trading=TradingActivityMetrics(
                bot_tx_pct=overrides.get("bot_tx_pct", 0.25),
            ),
            risk=RiskMetrics(
                rug_risk_score=overrides.get("rug_risk_score", 2.5),
                honeypot_flag=overrides.get("honeypot_flag", False),
            ),
            recommendation="hold",
            confidence=0.5,
            score=52.0,
            reasoning=["Heuristic baseline."],
        )

    # ── Inheritance & structure ────────────────────────────────────────────────

    def test_ai_dex_bot_is_subclass_of_dex_bot(self):
        from crypto_toolkit.trading.dex_bot import AIDexBot, DexBot
        assert issubclass(AIDexBot, DexBot)

    def test_ai_dex_bot_no_llm_attributes(self):
        """AIDexBot must not carry LLM-specific attributes."""
        from crypto_toolkit.trading.dex_bot import AIDexBot
        bot = AIDexBot()
        assert not hasattr(bot, "model"), "model attr should not exist on AIDexBot"
        assert not hasattr(bot, "llm_timeout"), "llm_timeout attr should not exist"

    def test_ai_dex_bot_has_ensemble(self):
        from crypto_toolkit.trading.dex_bot import AIDexBot, DexBotEnsemble
        bot = AIDexBot()
        assert isinstance(bot._ensemble, DexBotEnsemble)

    def test_ai_reasoning_field_defaults_to_none(self):
        report = self._make_dummy_report()
        assert report.ai_reasoning is None

    def test_report_to_dict_includes_ai_reasoning(self):
        report = self._make_dummy_report()
        report.ai_reasoning = "Local ML says buy."
        d = report.to_dict()
        assert "ai_reasoning" in d
        assert d["ai_reasoning"] == "Local ML says buy."

    def test_report_to_text_includes_ai_section(self):
        report = self._make_dummy_report()
        report.ai_reasoning = "Token looks good based on liquidity and low bot activity."
        text = report.to_text()
        assert "AI Analysis" in text
        assert "Token looks good" in text

    def test_report_to_text_no_ai_section_when_none(self):
        report = self._make_dummy_report()
        report.ai_reasoning = None
        text = report.to_text()
        assert "AI Analysis" not in text

    # ── Feature engineering ────────────────────────────────────────────────────

    def test_report_to_features_returns_all_columns(self):
        from crypto_toolkit.trading.dex_bot import _report_to_features, _DEX_FEATURE_COLS
        report = self._make_dummy_report()
        features = _report_to_features(report)
        for col in _DEX_FEATURE_COLS:
            assert col in features, f"Missing feature: {col}"

    def test_report_to_features_types_are_float(self):
        from crypto_toolkit.trading.dex_bot import _report_to_features
        report = self._make_dummy_report()
        features = _report_to_features(report)
        for k, v in features.items():
            assert isinstance(v, (int, float)), f"Feature {k} is not numeric: {type(v)}"

    def test_report_to_features_log_market_cap(self):
        from crypto_toolkit.trading.dex_bot import _report_to_features
        import math
        report = self._make_dummy_report(market_cap_usd=200_000)
        features = _report_to_features(report)
        assert features["log_market_cap"] == pytest.approx(math.log1p(200_000))

    def test_report_to_features_honeypot_is_float(self):
        from crypto_toolkit.trading.dex_bot import _report_to_features
        report = self._make_dummy_report(honeypot_flag=True)
        features = _report_to_features(report)
        assert features["honeypot_flag"] == 1.0

    # ── DexBotEnsemble ─────────────────────────────────────────────────────────

    def test_ensemble_trains_and_is_trained(self, tmp_path):
        from crypto_toolkit.trading.dex_bot import DexBotEnsemble
        ens = DexBotEnsemble(model_dir=tmp_path)
        assert not ens._trained
        ens.train(n_samples=300)   # small sample for speed
        assert ens._trained

    def test_ensemble_predict_returns_valid_recommendation(self, tmp_path):
        from crypto_toolkit.trading.dex_bot import DexBotEnsemble
        ens = DexBotEnsemble(model_dir=tmp_path)
        ens.train(n_samples=300)
        report = self._make_dummy_report()
        rec, conf, reasoning = ens.predict(report)
        assert rec in {"buy", "sell", "hold", "avoid"}
        assert 0.0 <= conf <= 1.0
        assert isinstance(reasoning, str) and len(reasoning) > 10

    def test_ensemble_reasoning_contains_recommendation(self, tmp_path):
        from crypto_toolkit.trading.dex_bot import DexBotEnsemble
        ens = DexBotEnsemble(model_dir=tmp_path)
        ens.train(n_samples=300)
        report = self._make_dummy_report()
        rec, conf, reasoning = ens.predict(report)
        assert rec.upper() in reasoning

    def test_ensemble_persists_and_reloads(self, tmp_path):
        from crypto_toolkit.trading.dex_bot import DexBotEnsemble
        ens1 = DexBotEnsemble(model_dir=tmp_path)
        ens1.train(n_samples=300)
        # A fresh instance loading from same dir should be trained
        ens2 = DexBotEnsemble(model_dir=tmp_path)
        assert ens2._trained

    def test_ensemble_predict_on_honeypot_mentions_flag(self, tmp_path):
        from crypto_toolkit.trading.dex_bot import DexBotEnsemble
        ens = DexBotEnsemble(model_dir=tmp_path)
        ens.train(n_samples=300)
        report = self._make_dummy_report(honeypot_flag=True, rug_risk_score=9.5)
        _, _, reasoning = ens.predict(report)
        # Honeypot and/or high rug risk should appear in the narrative
        assert "honeypot" in reasoning.lower() or "rug" in reasoning.lower()

    # ── _enrich_with_local_model ───────────────────────────────────────────────

    def test_enrich_with_local_model_overrides_recommendation(self, tmp_path):
        from crypto_toolkit.trading.dex_bot import AIDexBot, DexBotEnsemble
        bot = AIDexBot(model_dir=tmp_path)
        # Pre-train the ensemble
        bot._ensemble.train(n_samples=300)
        report = self._make_dummy_report()
        bot._enrich_with_local_model(report)
        # Recommendation is always overridden by ML
        assert report.recommendation in {"buy", "sell", "hold", "avoid"}
        assert report.ai_reasoning is not None
        assert any("[LocalML]" in r for r in report.reasoning)

    def test_enrich_with_local_model_silently_fails_on_error(self, tmp_path):
        """If the ensemble raises an exception, the report must be unchanged."""
        from crypto_toolkit.trading.dex_bot import AIDexBot
        bot = AIDexBot(model_dir=tmp_path)
        # Force predict() to raise
        bot._ensemble.predict = MagicMock(side_effect=RuntimeError("boom"))
        report = self._make_dummy_report()
        original_rec = report.recommendation
        bot._enrich_with_local_model(report)
        assert report.recommendation == original_rec
        assert report.ai_reasoning is None

    # ── Full async pipeline ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_analyse_full_pipeline_with_local_model(self, tmp_path):
        """End-to-end: all data fetchers mocked; local ML runs for real."""
        from crypto_toolkit.trading.dex_bot import (
            AIDexBot, TokenInfo, SocialMetrics,
            TradingActivityMetrics, RiskMetrics,
        )

        bot = AIDexBot(model_dir=tmp_path)
        # Pre-train with a small sample
        bot._ensemble.train(n_samples=300)

        dummy_token = TokenInfo(
            address="0xtest", chain="ethereum", name="Mock", symbol="MCK",
            price_usd=0.001, market_cap_usd=100_000,
            liquidity_usd=20_000, volume_24h_usd=5_000,
            age_days=30, holder_count=300,
        )
        dummy_social   = SocialMetrics(hype_score=4.0, sentiment_score=0.5)
        dummy_trading  = TradingActivityMetrics(bot_tx_pct=0.3)
        dummy_risk     = RiskMetrics(rug_risk_score=3.0)

        bot._fetch_token_info         = AsyncMock(return_value=dummy_token)
        bot._fetch_social_metrics     = AsyncMock(return_value=dummy_social)
        bot._analyse_trading_activity = AsyncMock(return_value=dummy_trading)
        bot._assess_risk              = AsyncMock(return_value=dummy_risk)

        report = await bot.analyse("0xtest", chain="ethereum")

        assert report.recommendation in {"buy", "sell", "avoid", "hold"}
        assert 0.0 <= report.confidence <= 1.0
        assert report.ai_reasoning is not None
        assert 0.0 <= report.score <= 100.0

    # ── Agent skill ────────────────────────────────────────────────────────────

    def test_ai_dex_bot_skill_in_registry(self):
        from crypto_toolkit.ai.agent_skills import TOOL_REGISTRY
        assert "ai_dex_bot_analyse" in TOOL_REGISTRY

    def test_ai_dex_bot_skill_no_model_param(self):
        """The local-ML skill must not expose a 'model' parameter."""
        from crypto_toolkit.ai.agent_skills import TOOL_REGISTRY
        skill = TOOL_REGISTRY["ai_dex_bot_analyse"]
        schema = skill.openai_schema()
        props = schema["function"]["parameters"].get("properties", {})
        assert "model" not in props, "'model' should not be a parameter of the local-ML skill"

    def test_ai_dex_bot_skill_openai_schema(self):
        from crypto_toolkit.ai.agent_skills import TOOL_REGISTRY
        skill = TOOL_REGISTRY["ai_dex_bot_analyse"]
        schema = skill.openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "ai_dex_bot_analyse"
        props = schema["function"]["parameters"].get("properties", {})
        assert "token_address" in props

    def test_ai_dex_bot_skill_anthropic_schema(self):
        from crypto_toolkit.ai.agent_skills import TOOL_REGISTRY
        skill = TOOL_REGISTRY["ai_dex_bot_analyse"]
        schema = skill.anthropic_schema()
        assert schema["name"] == "ai_dex_bot_analyse"
        assert "input_schema" in schema

    def test_get_all_schemas_includes_ai_dex_bot(self):
        from crypto_toolkit.ai.agent_skills import get_all_schemas
        schemas = get_all_schemas("openai")
        names = [s["function"]["name"] for s in schemas]
        assert "ai_dex_bot_analyse" in names
