package handler

import "testing"

func TestClaimCallbackMessageFirstClickWins(t *testing.T) {
	if !claimCallbackMessage(1, 100) {
		t.Fatal("first click should be claimed")
	}
	if claimCallbackMessage(1, 100) {
		t.Fatal("second click on same message must be rejected")
	}
	if !claimCallbackMessage(1, 101) || !claimCallbackMessage(2, 100) {
		t.Fatal("different message/chat should be independent")
	}
}
