from __future__ import annotations

import torch

from app.models.tft import (
    GLU,
    DemandTFT,
    GatedResidualNetwork,
    InterpretableMultiHeadAttention,
    VariableSelectionNetwork,
)


class TestGLU:
    def test_output_shape_matches_output_size(self):
        glu = GLU(input_size=10, output_size=6)
        x = torch.randn(4, 10)

        assert glu(x).shape == (4, 6)

    def test_defaults_output_size_to_input_size(self):
        glu = GLU(input_size=8)
        x = torch.randn(4, 8)

        assert glu(x).shape == (4, 8)


class TestGatedResidualNetwork:
    def test_output_shape_with_projected_residual(self):
        grn = GatedResidualNetwork(input_size=10, hidden_size=16, output_size=6)
        x = torch.randn(4, 10)

        assert grn(x).shape == (4, 6)

    def test_incorporates_a_context_vector_without_shape_error(self):
        grn = GatedResidualNetwork(
            input_size=10, hidden_size=16, output_size=6, context_size=3
        )
        x = torch.randn(4, 10)
        context = torch.randn(4, 3)

        out = grn(x, context=context)

        assert out.shape == (4, 6)

    def test_context_actually_changes_the_output(self):
        torch.manual_seed(0)
        grn = GatedResidualNetwork(
            input_size=10, hidden_size=16, output_size=6, context_size=3
        )
        x = torch.randn(4, 10)

        out_no_context = grn(x)
        out_with_context = grn(x, context=torch.randn(4, 3))

        assert not torch.allclose(out_no_context, out_with_context)


class TestVariableSelectionNetwork:
    def test_output_shapes(self):
        vsn = VariableSelectionNetwork(n_vars=5, hidden_size=8)
        x = torch.randn(4, 12, 5)  # (batch, seq, n_vars)

        selected, weights = vsn(x)

        assert selected.shape == (4, 12, 8)
        assert weights.shape == (4, 12, 5)

    def test_selection_weights_sum_to_one(self):
        vsn = VariableSelectionNetwork(n_vars=5, hidden_size=8)
        x = torch.randn(4, 12, 5)

        _, weights = vsn(x)

        assert torch.allclose(weights.sum(dim=-1), torch.ones(4, 12), atol=1e-5)


class TestInterpretableMultiHeadAttention:
    def test_output_shape(self):
        attn = InterpretableMultiHeadAttention(d_model=16, n_heads=4)
        x = torch.randn(2, 6, 16)

        out, weights = attn(x)

        assert out.shape == (2, 6, 16)
        assert weights.shape == (2, 6, 6)

    def test_causal_mask_zeroes_out_future_attention(self):
        attn = InterpretableMultiHeadAttention(d_model=16, n_heads=4, dropout=0.0)
        x = torch.randn(2, 6, 16)
        mask = torch.triu(torch.ones(6, 6, dtype=torch.bool), diagonal=1)

        _, weights = attn(x, mask=mask)

        # position i must never attend to any position j > i.
        upper = torch.triu(weights, diagonal=1)
        assert torch.allclose(upper, torch.zeros_like(upper), atol=1e-6)

    def test_rejects_d_model_not_divisible_by_n_heads(self):
        import pytest

        with pytest.raises(ValueError):
            InterpretableMultiHeadAttention(d_model=10, n_heads=3)


class TestDemandTFT:
    def _model(self, **kwargs):
        defaults = dict(
            n_encoder_features=10,
            n_decoder_features=4,
            horizon=6,
            hidden_size=8,
            n_heads=2,
            dropout=0.0,
        )
        defaults.update(kwargs)
        return DemandTFT(**defaults)

    def test_forward_pass_produces_correct_shapes(self):
        model = self._model()
        x_enc = torch.randn(4, 12, 10)
        x_dec = torch.randn(4, 6, 4)

        out = model(x_enc, x_dec)

        assert out.p10.shape == (4, 6)
        assert out.p50.shape == (4, 6)
        assert out.p90.shape == (4, 6)

    def test_quantiles_never_cross_at_init(self):
        torch.manual_seed(0)
        model = self._model()
        x_enc = torch.randn(8, 12, 10)
        x_dec = torch.randn(8, 6, 4)

        out = model(x_enc, x_dec)

        assert (out.p10 <= out.p50).all()
        assert (out.p50 <= out.p90).all()

    def test_backward_pass_produces_no_nan_gradients(self):
        torch.manual_seed(0)
        model = self._model()
        x_enc = torch.randn(4, 12, 10)
        x_dec = torch.randn(4, 6, 4)
        target = torch.randn(4, 6)

        out = model(x_enc, x_dec)
        loss = (out.p50 - target).pow(2).mean()
        loss.backward()

        for p in model.parameters():
            if p.grad is not None:
                assert not torch.isnan(p.grad).any()

    def test_changing_a_future_decoder_step_does_not_change_earlier_output(self):
        """Causal masking's real, observable consequence: forecast step 1
        must not depend on decoder inputs for step 3 -- verifies the
        causal mask is actually wired correctly end to end through
        `DemandTFT.forward`, not just unit-tested on the attention layer
        in isolation."""
        torch.manual_seed(0)
        model = self._model(horizon=3)
        model.eval()
        x_enc = torch.randn(1, 12, 10)
        x_dec = torch.randn(1, 3, 4)

        out_a = model(x_enc, x_dec)

        x_dec_changed = x_dec.clone()
        x_dec_changed[:, 2, :] = torch.randn(1, 4)  # perturb only the last step
        out_b = model(x_enc, x_dec_changed)

        assert torch.allclose(out_a.p50[:, 0], out_b.p50[:, 0], atol=1e-5)
        assert torch.allclose(out_a.p50[:, 1], out_b.p50[:, 1], atol=1e-5)
