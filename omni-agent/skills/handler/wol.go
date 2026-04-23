package handler

import (
	"context"
	"errors"
	"net"
	"os"
	"regexp"

	"github.com/jackc/pgx/v5/pgxpool"
)

// HandleWOL sends a Wake-on-LAN magic packet.
func HandleWOL(db *pgxpool.Pool, params map[string]interface{}) (interface{}, error) {
	mac, ok := params["mac"].(string)
	if !ok {
		// Try target_name lookup in DB
		targetName, ok := params["target_name"].(string)
		if !ok {
			return nil, errors.New("mac address or target_name is required")
		}

		if db == nil {
			return nil, errors.New("db unavailable and no mac provided")
		}

		err := db.QueryRow(context.Background(),
			"SELECT mac FROM wol_targets WHERE ai_name = $1 OR label = $1",
			targetName).Scan(&mac)
		if err != nil {
			return nil, errors.New("target not found")
		}
	}

	// Validate MAC address format
	matched, _ := regexp.MatchString(`^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$`, mac)
	if !matched {
		return nil, errors.New("invalid mac address format")
	}

	hwAddr, err := net.ParseMAC(mac)
	if err != nil {
		return nil, err
	}

	broadcast := os.Getenv("WOL_BROADCAST")
	if broadcast == "" {
		broadcast = "255.255.255.255"
	}

	addr, err := net.ResolveUDPAddr("udp", broadcast+":9")
	if err != nil {
		return nil, err
	}

	// Magic Packet: 6 bytes of 0xFF followed by 16 repetitions of the MAC address
	payload := make([]byte, 102)
	for i := 0; i < 6; i++ {
		payload[i] = 0xff
	}
	for i := 1; i <= 16; i++ {
		copy(payload[i*6:], hwAddr)
	}

	conn, err := net.DialUDP("udp", nil, addr)
	if err != nil {
		return nil, err
	}
	defer conn.Close()

	_, err = conn.Write(payload)
	if err != nil {
		return nil, err
	}

	return map[string]string{
		"status":    "sent",
		"mac":       mac,
		"broadcast": broadcast,
	}, nil
}
